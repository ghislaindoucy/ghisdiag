"""
Ghisdiag - Generateur de charge GPU (bench thermique GPU).

Chauffe le GPU de maniere reproductible via un *compute shader* Direct3D 11
(boucle FMA saturante), pour le bench thermique GPU (GPU_BENCH_PROGRESS.md).
Vendor-neutral : marche sur tout GPU WDDM (NVIDIA / AMD / Intel, dedie ou
integre), sans binaire supplementaire (d3d11.dll / dxgi.dll / d3dcompiler_47.dll
sont des composants de Windows).

Pilote D3D11 en ctypes/COM (aucune dependance Python). Concu comme cpu_load.py :
script autonome + mode worker en version figee (relance de l'exe avec
--ghisdiag-gpu-load-worker, gere dans main.py).

    py -m collectors.gpu_load --list                 # enumere les adaptateurs
    py -m collectors.gpu_load --probe 0              # cree un device (test)
    py -m collectors.gpu_load --selftest --adapter NVIDIA   # 1 dispatch + mesure
    py -m collectors.gpu_load --adapter NVIDIA --duration 60 --intensity 100

PIEGES (voir GPU_BENCH_PROGRESS.md) :
  - TDR : jamais un dispatch long (> ~2 s) sinon Windows reset le pilote. On
    calibre la taille de dispatch pour rester ~40 ms, boucle courte, avec
    synchronisation (CopyResource -> Map) qui borne la file GPU a 1.
  - Adaptateur : device sur un adaptateur MATERIEL choisi (jamais WARP), et sur
    le MEME GPU que celui mesure (matching par nom).
"""

import ctypes
import logging
import os
import signal
import sys
import time
from ctypes import (POINTER, byref, c_char_p, c_float, c_int32, c_uint,
                    c_uint32, c_uint16, c_ubyte, c_ulong, c_void_p, c_size_t,
                    c_wchar, cast, create_string_buffer)
from ctypes import WINFUNCTYPE, Structure
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# --- Constantes D3D11 / DXGI ------------------------------------------------

_DXGI_ERROR_NOT_FOUND = -2005270526  # 0x887A0002

D3D_DRIVER_TYPE_UNKNOWN  = 0
D3D_FEATURE_LEVEL_11_0   = 0xb000
D3D_FEATURE_LEVEL_10_1   = 0xa100
D3D_FEATURE_LEVEL_10_0   = 0xa000
D3D11_SDK_VERSION        = 7

DXGI_ADAPTER_FLAG_SOFTWARE = 0x2

D3D11_USAGE_DEFAULT = 0
D3D11_USAGE_STAGING = 3
D3D11_BIND_UNORDERED_ACCESS         = 0x80
D3D11_CPU_ACCESS_READ               = 0x20000
D3D11_RESOURCE_MISC_BUFFER_STRUCTURED = 0x40
D3D11_UAV_DIMENSION_BUFFER          = 1
D3D11_MAP_READ                      = 1
DXGI_FORMAT_UNKNOWN                 = 0

D3DCOMPILE_OPTIMIZATION_LEVEL3      = 1 << 15

_VENDOR_IDS = {
    0x10DE: "NVIDIA", 0x1002: "AMD", 0x1022: "AMD",
    0x8086: "Intel", 0x1414: "Microsoft",
}

# Indices de vtable (headers D3D11/DXGI). Une erreur ici = crash : verifies.
_VT_RELEASE          = 2      # IUnknown::Release
_VT_ENUM_ADAPTERS1   = 12     # IDXGIFactory1::EnumAdapters1
_VT_GET_DESC1        = 10     # IDXGIAdapter1::GetDesc1
# ID3D11Device
_VT_CREATE_BUFFER    = 3
_VT_CREATE_UAV       = 8
_VT_CREATE_CS        = 18
# ID3D11DeviceContext
_VT_CTX_MAP          = 14
_VT_CTX_UNMAP        = 15
_VT_CTX_DISPATCH     = 41
_VT_CTX_COPY_RESOURCE = 47
_VT_CTX_CS_SET_UAV   = 68
_VT_CTX_CS_SET_SHADER = 69
_VT_CTX_FLUSH        = 111
# ID3DBlob
_VT_BLOB_GET_PTR     = 3
_VT_BLOB_GET_SIZE    = 4


# --- COM : appel d'une methode par index de vtable --------------------------

class GUID(Structure):
    _fields_ = [("Data1", c_uint32), ("Data2", c_uint16),
                ("Data3", c_uint16), ("Data4", c_ubyte * 8)]


def _guid(d1, d2, d3, *rest) -> GUID:
    g = GUID()
    g.Data1, g.Data2, g.Data3 = d1, d2, d3
    g.Data4 = (c_ubyte * 8)(*rest)
    return g


IID_IDXGIFactory1 = _guid(0x770aae78, 0xf26f, 0x4dba,
                          0xa8, 0x29, 0x25, 0x3c, 0x83, 0xd1, 0xb3, 0x87)


def _com(this, index, restype, *argtypes):
    vtbl = cast(this, POINTER(c_void_p))[0]
    fnp = cast(vtbl, POINTER(c_void_p))[index]
    return WINFUNCTYPE(restype, c_void_p, *argtypes)(fnp)


def _release(p) -> None:
    if p:
        try:
            _com(p, _VT_RELEASE, c_ulong)(p)
        except Exception:
            pass


# --- Structures ------------------------------------------------------------

class DXGI_ADAPTER_DESC1(Structure):
    _fields_ = [
        ("Description", c_wchar * 128),
        ("VendorId", c_uint), ("DeviceId", c_uint),
        ("SubSysId", c_uint), ("Revision", c_uint),
        ("DedicatedVideoMemory", c_size_t),
        ("DedicatedSystemMemory", c_size_t),
        ("SharedSystemMemory", c_size_t),
        ("AdapterLuid_Low", c_uint32), ("AdapterLuid_High", c_int32),
        ("Flags", c_uint),
    ]


class D3D11_BUFFER_DESC(Structure):
    _fields_ = [
        ("ByteWidth", c_uint), ("Usage", c_uint),
        ("BindFlags", c_uint), ("CPUAccessFlags", c_uint),
        ("MiscFlags", c_uint), ("StructureByteStride", c_uint),
    ]


class D3D11_UAV_DESC(Structure):
    # Format, ViewDimension, puis union (3 UINT au plus large = Buffer).
    _fields_ = [
        ("Format", c_uint), ("ViewDimension", c_uint),
        ("FirstElement", c_uint), ("NumElements", c_uint), ("Flags", c_uint),
    ]


class D3D11_MAPPED_SUBRESOURCE(Structure):
    _fields_ = [("pData", c_void_p), ("RowPitch", c_uint), ("DepthPitch", c_uint)]


# --- Chargement des DLL systeme ---------------------------------------------

def _system32(dll: str) -> Optional[ctypes.WinDLL]:
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    for cand in (str(Path(sysroot) / "System32" / dll), dll):
        try:
            return ctypes.WinDLL(cand)
        except OSError:
            continue
    return None


def available() -> bool:
    """D3D11 + DXGI + compilateur de shader chargeables ? (composants Windows)."""
    return all(_system32(d) is not None
               for d in ("d3d11.dll", "dxgi.dll", "d3dcompiler_47.dll"))


# --- Enumeration des adaptateurs --------------------------------------------

def list_adapters() -> list[dict]:
    """Liste les adaptateurs via DXGI. Adaptateurs LOGICIELS marques
    is_software=True (le bench doit les ecarter)."""
    dxgi = _system32("dxgi.dll")
    if dxgi is None:
        return []
    create_factory = getattr(dxgi, "CreateDXGIFactory1", None)
    if create_factory is None:
        return []
    create_factory.restype = c_int32
    create_factory.argtypes = [POINTER(GUID), POINTER(c_void_p)]

    factory = c_void_p()
    if create_factory(byref(IID_IDXGIFactory1), byref(factory)) < 0 or not factory:
        return []

    out: list[dict] = []
    try:
        i = 0
        while i <= 32:
            adapter = c_void_p()
            hr = _com(factory, _VT_ENUM_ADAPTERS1, c_int32,
                      c_uint, POINTER(c_void_p))(factory, i, byref(adapter))
            if hr == _DXGI_ERROR_NOT_FOUND or hr < 0 or not adapter:
                break
            try:
                desc = DXGI_ADAPTER_DESC1()
                if _com(adapter, _VT_GET_DESC1, c_int32,
                        POINTER(DXGI_ADAPTER_DESC1))(adapter, byref(desc)) >= 0:
                    is_sw = bool(desc.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) or \
                        desc.VendorId == 0x1414
                    out.append({
                        "index": i, "name": desc.Description,
                        "vendor": _VENDOR_IDS.get(desc.VendorId, "?"),
                        "vendor_id": desc.VendorId, "device_id": desc.DeviceId,
                        "vram_mb": round(desc.DedicatedVideoMemory / (1024 * 1024)),
                        "luid": (desc.AdapterLuid_High << 32) | desc.AdapterLuid_Low,
                        "is_software": is_sw,
                    })
            finally:
                _release(adapter)
            i += 1
    finally:
        _release(factory)
    return out


def _match_adapter(adapters: list[dict], selector) -> Optional[dict]:
    """Adaptateur MATERIEL selon selector (index int, sous-chaine du nom, ou
    None = le GPU dedie le plus gros). None si aucun materiel."""
    hw = [a for a in adapters if not a["is_software"]]
    if not hw:
        return None
    if selector is None:
        return max(hw, key=lambda a: a["vram_mb"])
    if isinstance(selector, int):
        return next((a for a in hw if a["index"] == selector), None)
    sel = str(selector).lower()
    return next((a for a in hw if sel in a["name"].lower()), None)


# --- Compilation du compute shader (d3dcompiler_47.dll) ---------------------

# RWStructuredBuffer + boucle FMA : sature les ALU du GPU (chaleur). Le nombre
# d'iterations est injecte a la compilation ; l'index modulo N garde un buffer
# minuscule (copie/sync bon marche).
_HLSL_TEMPLATE = """
RWStructuredBuffer<float> Out : register(u0);
[numthreads(64, 1, 1)]
void main(uint3 tid : SV_DispatchThreadID) {{
    float a = (float)(tid.x % 977) * 1.0001f + 1.0f;
    float b = 0.5f;
    [loop]
    for (int i = 0; i < {iters}; i++) {{
        a = mad(a, 1.0000003f, b);
        b = mad(b, 0.9999997f, a);
        a = a - floor(a);
        b = b - floor(b);
    }}
    Out[tid.x % {nbuf}] = a + b;
}}
"""

_NBUF = 1024   # elements du buffer de sortie (4 Ko)


def _compile_cs(iters: int) -> Optional[bytes]:
    comp = _system32("d3dcompiler_47.dll")
    if comp is None:
        return None
    D3DCompile = comp.D3DCompile
    D3DCompile.restype = c_int32
    D3DCompile.argtypes = [
        c_void_p, c_size_t, c_char_p, c_void_p, c_void_p,
        c_char_p, c_char_p, c_uint, c_uint,
        POINTER(c_void_p), POINTER(c_void_p),
    ]
    src = _HLSL_TEMPLATE.format(iters=int(iters), nbuf=_NBUF).encode("ascii")
    code = c_void_p()
    errs = c_void_p()
    hr = D3DCompile(src, len(src), b"ghisdiag_cs", None, None,
                    b"main", b"cs_5_0", D3DCOMPILE_OPTIMIZATION_LEVEL3, 0,
                    byref(code), byref(errs))
    try:
        if hr < 0 or not code:
            if errs:
                ptr = _com(errs, _VT_BLOB_GET_PTR, c_void_p)(errs)
                msg = ctypes.string_at(ptr) if ptr else b""
                logger.error("D3DCompile: %s", msg.decode("ascii", "replace"))
            return None
        ptr = _com(code, _VT_BLOB_GET_PTR, c_void_p)(code)
        size = _com(code, _VT_BLOB_GET_SIZE, c_size_t)(code)
        return ctypes.string_at(ptr, size)
    finally:
        _release(code)
        _release(errs)


# --- Generateur de charge ---------------------------------------------------

class GpuLoad:
    """Pipeline compute D3D11 : device + shader + buffer/UAV + boucle de dispatch.

    setup() prepare tout sur l'adaptateur choisi ; run() chauffe jusqu'a
    l'echeance ; close() libere. Chaque dispatch est calibre pour rester court
    (anti-TDR) et suivi d'une synchro (CopyResource -> Map) qui borne la file."""

    def __init__(self, iters: int = 1536):
        self.iters = iters
        self.device = c_void_p()
        self.context = c_void_p()
        self.shader = c_void_p()
        self.buffer = c_void_p()
        self.staging = c_void_p()
        self.uav = c_void_p()
        self.adapter_name = ""
        self._groups = 2048   # calibre au 1er dispatch

    def setup(self, adapter_info: dict) -> bool:
        if not self._create_device(adapter_info):
            return False
        code = _compile_cs(self.iters)
        if not code:
            logger.error("Compilation du compute shader impossible.")
            return False
        d = self.device
        # Compute shader
        hr = _com(d, _VT_CREATE_CS, c_int32,
                  c_void_p, c_size_t, c_void_p, POINTER(c_void_p))(
                      d, code, len(code), None, byref(self.shader))
        if hr < 0 or not self.shader:
            logger.error("CreateComputeShader hr=0x%08x", hr & 0xFFFFFFFF)
            return False
        # Buffer de sortie (UAV, structured)
        bd = D3D11_BUFFER_DESC(ByteWidth=_NBUF * 4, Usage=D3D11_USAGE_DEFAULT,
                               BindFlags=D3D11_BIND_UNORDERED_ACCESS,
                               CPUAccessFlags=0,
                               MiscFlags=D3D11_RESOURCE_MISC_BUFFER_STRUCTURED,
                               StructureByteStride=4)
        hr = _com(d, _VT_CREATE_BUFFER, c_int32,
                  POINTER(D3D11_BUFFER_DESC), c_void_p, POINTER(c_void_p))(
                      d, byref(bd), None, byref(self.buffer))
        if hr < 0 or not self.buffer:
            logger.error("CreateBuffer(UAV) hr=0x%08x", hr & 0xFFFFFFFF)
            return False
        # UAV sur ce buffer
        ud = D3D11_UAV_DESC(Format=DXGI_FORMAT_UNKNOWN,
                            ViewDimension=D3D11_UAV_DIMENSION_BUFFER,
                            FirstElement=0, NumElements=_NBUF, Flags=0)
        hr = _com(d, _VT_CREATE_UAV, c_int32,
                  c_void_p, POINTER(D3D11_UAV_DESC), POINTER(c_void_p))(
                      d, self.buffer, byref(ud), byref(self.uav))
        if hr < 0 or not self.uav:
            logger.error("CreateUnorderedAccessView hr=0x%08x", hr & 0xFFFFFFFF)
            return False
        # Buffer staging (lecture CPU -> synchro)
        sd = D3D11_BUFFER_DESC(ByteWidth=_NBUF * 4, Usage=D3D11_USAGE_STAGING,
                               BindFlags=0, CPUAccessFlags=D3D11_CPU_ACCESS_READ,
                               MiscFlags=0, StructureByteStride=0)
        hr = _com(d, _VT_CREATE_BUFFER, c_int32,
                  POINTER(D3D11_BUFFER_DESC), c_void_p, POINTER(c_void_p))(
                      d, byref(sd), None, byref(self.staging))
        if hr < 0 or not self.staging:
            logger.error("CreateBuffer(staging) hr=0x%08x", hr & 0xFFFFFFFF)
            return False
        # Bind : shader + UAV (une fois pour toutes)
        uav_arr = (c_void_p * 1)(self.uav)
        _com(self.context, _VT_CTX_CS_SET_SHADER, None,
             c_void_p, c_void_p, c_uint)(self.context, self.shader, None, 0)
        _com(self.context, _VT_CTX_CS_SET_UAV, None,
             c_uint, c_uint, POINTER(c_void_p), POINTER(c_uint))(
                 self.context, 0, 1, uav_arr, None)
        return True

    def _dispatch_sync(self, groups: int) -> float:
        """Un dispatch de `groups` groupes + synchro bloquante. Retourne la duree."""
        t0 = time.perf_counter()
        _com(self.context, _VT_CTX_DISPATCH, None,
             c_uint, c_uint, c_uint)(self.context, groups, 1, 1)
        _com(self.context, _VT_CTX_COPY_RESOURCE, None,
             c_void_p, c_void_p)(self.context, self.staging, self.buffer)
        mapped = D3D11_MAPPED_SUBRESOURCE()
        hr = _com(self.context, _VT_CTX_MAP, c_int32,
                  c_void_p, c_uint, c_uint, c_uint,
                  POINTER(D3D11_MAPPED_SUBRESOURCE))(
                      self.context, self.staging, 0, D3D11_MAP_READ, 0, byref(mapped))
        if hr >= 0:
            _com(self.context, _VT_CTX_UNMAP, None,
                 c_void_p, c_uint)(self.context, self.staging, 0)
        return time.perf_counter() - t0

    def _calibrate(self) -> None:
        """Ajuste le nombre de groupes pour qu'un dispatch dure ~40 ms (marge
        50x sous la limite TDR de 2 s).

        Le PREMIER dispatch est lent (JIT du shader + driver) : on jette
        quelques dispatches de chauffe, PUIS on monte le nombre de groupes
        jusqu'a un dispatch reellement domine par le calcul (>= 20 ms) avant
        d'extrapoler lineairement vers la cible. Extrapoler depuis un dispatch
        court (domine par l'overhead de submission/Map) surestimerait la charge."""
        target = 0.040
        for _ in range(3):
            self._dispatch_sync(512)          # chauffe (JIT)
        g = 1024
        dt = 0.0
        for _ in range(14):
            dt = min(self._dispatch_sync(g), self._dispatch_sync(g))
            if dt >= 0.020:
                break
            g = min(1 << 20, g * 4)
        if dt > 0:
            g = max(256, min(1 << 21, int(g * target / dt)))
        self._groups = g
        logger.info("GpuLoad calibre : %d groupes (~40 ms/dispatch vise)", g)

    def run(self, intensity: int, duration: float, cancel=None) -> None:
        """Chauffe jusqu'a `duration` secondes (0 = infini). intensity 1..100 =
        rapport cyclique. cancel() -> bool : arret anticipe optionnel."""
        self._calibrate()
        intensity = max(1, min(100, intensity))
        deadline = time.perf_counter() + duration if duration > 0 else float("inf")
        while time.perf_counter() < deadline:
            if cancel is not None and cancel():
                return
            dt = self._dispatch_sync(self._groups)
            if intensity < 100 and dt > 0:
                time.sleep(dt * (100 - intensity) / intensity)

    def _create_device(self, adapter_info: dict) -> bool:
        d3d11 = _system32("d3d11.dll")
        dxgi = _system32("dxgi.dll")
        if d3d11 is None or dxgi is None:
            return False
        create_factory = dxgi.CreateDXGIFactory1
        create_factory.restype = c_int32
        create_factory.argtypes = [POINTER(GUID), POINTER(c_void_p)]
        factory = c_void_p()
        if create_factory(byref(IID_IDXGIFactory1), byref(factory)) < 0 or not factory:
            return False
        adapter = c_void_p()
        try:
            hr = _com(factory, _VT_ENUM_ADAPTERS1, c_int32,
                      c_uint, POINTER(c_void_p))(factory, adapter_info["index"],
                                                 byref(adapter))
            if hr < 0 or not adapter:
                return False
            create_device = d3d11.D3D11CreateDevice
            create_device.restype = c_int32
            create_device.argtypes = [
                c_void_p, c_uint, c_void_p, c_uint, POINTER(c_uint), c_uint,
                c_uint, POINTER(c_void_p), POINTER(c_uint), POINTER(c_void_p),
            ]
            levels = (c_uint * 3)(D3D_FEATURE_LEVEL_11_0, D3D_FEATURE_LEVEL_10_1,
                                  D3D_FEATURE_LEVEL_10_0)
            fl = c_uint(0)
            hr = create_device(adapter, D3D_DRIVER_TYPE_UNKNOWN, None, 0,
                               levels, 3, D3D11_SDK_VERSION,
                               byref(self.device), byref(fl), byref(self.context))
            if hr < 0 or not self.device:
                logger.error("D3D11CreateDevice hr=0x%08x", hr & 0xFFFFFFFF)
                return False
            self.adapter_name = adapter_info["name"]
            return True
        finally:
            _release(adapter)
            _release(factory)

    def close(self) -> None:
        for p in (self.uav, self.staging, self.buffer, self.shader,
                  self.context, self.device):
            _release(p)
        self.uav = self.staging = self.buffer = self.shader = c_void_p()
        self.context = self.device = c_void_p()


# --- CLI / worker -----------------------------------------------------------

def _print_adapters(adapters: list[dict]) -> None:
    print(f"{len(adapters)} adaptateur(s) :")
    for a in adapters:
        tag = " [LOGICIEL]" if a["is_software"] else ""
        print(f"  [{a['index']}] {a['name']} ({a['vendor']}) "
              f"{a['vram_mb']} Mo VRAM{tag}")


def _cli() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="GPU load generator (D3D11 compute)")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--probe", type=int, metavar="INDEX")
    parser.add_argument("--selftest", action="store_true",
                        help="setup + calibrage + quelques dispatches, puis rapport")
    parser.add_argument("--adapter", default=None,
                        help="index ou sous-chaine du nom (defaut: dGPU le plus gros)")
    parser.add_argument("--intensity", type=int, default=100)
    parser.add_argument("--duration", type=int, default=0)
    args = parser.parse_args()

    if not available():
        print("D3D11 / DXGI / d3dcompiler indisponibles sur cette machine.")
        return 2
    adapters = list_adapters()

    if args.list:
        _print_adapters(adapters)
        return 0

    if args.probe is not None:
        info = _match_adapter(adapters, args.probe)
        if info is None:
            print(f"Adaptateur {args.probe} introuvable ou logiciel.")
            return 1
        load = GpuLoad()
        ok = load._create_device(info)
        print(f"Device sur [{info['index']}] {info['name']} : "
              f"{'OK' if ok else 'ECHEC'}")
        load.close()
        return 0 if ok else 1

    # Selection de l'adaptateur de charge.
    sel = args.adapter
    if sel is not None and sel.isdigit():
        sel = int(sel)
    info = _match_adapter(adapters, sel)
    if info is None:
        print("Aucun adaptateur materiel utilisable.")
        _print_adapters(adapters)
        return 1

    if args.selftest:
        load = GpuLoad()
        if not load.setup(info):
            print(f"setup ECHEC sur {info['name']}")
            load.close()
            return 1
        load._calibrate()
        dts = [load._dispatch_sync(load._groups) for _ in range(5)]
        load.close()
        avg = sum(dts) / len(dts) * 1000
        print(f"selftest OK sur [{info['index']}] {info['name']} : "
              f"{load._groups} groupes, {avg:.1f} ms/dispatch moyen")
        return 0

    # Mode charge reelle.
    load = GpuLoad()
    if not load.setup(info):
        print(f"setup ECHEC sur {info['name']}")
        load.close()
        return 1
    print(f"Charge GPU sur [{info['index']}] {info['name']} "
          f"(intensite {args.intensity}%, duree {args.duration or 'infini'} s)")
    try:
        load.run(args.intensity, args.duration)
    except KeyboardInterrupt:
        pass
    finally:
        load.close()
    return 0


def main() -> None:
    # Enfant tue par le parent : on ignore SIGTERM comme cpu_load (le parent tue
    # l'arbre via taskkill /T).
    try:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    except Exception:
        pass
    sys.exit(_cli())


if __name__ == "__main__":
    main()
