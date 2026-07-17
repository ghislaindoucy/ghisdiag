"""
Ghisdiag - Sonde de terrain pour le chantier bench GPU (GPU_BENCH_PROGRESS.md).

Ecrit un rapport JSON dans le meme dossier que ce script (donc sur la cle USB),
nomme par machine + horodatage, pour comparer facilement plusieurs postes
d'atelier sans rien ecraser.

Chaque section est isolee (try/except) : une source indisponible n'empeche pas
la collecte des autres. Aucune elevation requise (mais tourner en admin donne
des resultats plus complets : CPU/carte mere via PawnIO).

Usage : py atelier_probe.py   (ou double-clic sur test_gpu_atelier.bat)
"""

import ctypes
import json
import os
import platform
import socket
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Autorise `python atelier_probe.py` depuis n'importe quel dossier courant :
# on ajoute le dossier du script (racine du projet) en tete de sys.path.
_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(_ROOT))


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _section(name: str, fn):
    """Execute fn() ; capture resultat ou erreur, ne leve jamais."""
    try:
        return {"ok": True, "data": fn()}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()}


def collect() -> dict:
    report: dict = {}

    report["meta"] = {
        "hostname":     socket.gethostname(),
        "os":           platform.platform(),
        "python":       sys.version,
        "is_admin":     _is_admin(),
        "timestamp":    datetime.now().isoformat(timespec="seconds"),
        "script_dir":   str(_ROOT),
        "cwd":          os.getcwd(),
    }

    # --- Dossier tools : presence des DLL / driver, sans lancer d'install ---
    def _tools():
        from collectors import lhm_backend
        info = lhm_backend.info()
        d = Path(info["active_dir"])
        info["active_dir_contents"] = (sorted(p.name for p in d.iterdir())
                                       if d.is_dir() else [])
        return info
    report["tools_dir"] = _section("tools_dir", _tools)

    # --- PawnIO (driver CPU/carte mere) : etat seulement, aucune install ---
    def _pawnio():
        from collectors import pawnio
        return {
            "installer_available": pawnio.installer_available(),
            "pawnio_installed":    pawnio.pawnio_installed(),
        }
    report["pawnio"] = _section("pawnio", _pawnio)

    # --- NVML brut (GPU NVIDIA uniquement) ---
    def _nvml():
        from collectors import gpu
        return {"available": gpu.available(), "read": gpu.read()}
    report["nvml"] = _section("nvml", _nvml)

    # --- API unifiee (NVIDIA via NVML, sinon repli LHM) : le coeur du test M1 ---
    def _list_gpus():
        from collectors import gpu
        return gpu.list_gpus()
    report["list_gpus"] = _section("list_gpus", _list_gpus)

    # --- Flux LHM brut (tous vendors) : cle pour verifier gpu_name/clock/power ---
    def _lhm_sample():
        from collectors import sensors
        return {
            "lhm_available": sensors.lhm_available(),
            "sample":        sensors.read_once(timeout=25),
        }
    report["lhm_sample"] = _section("lhm_sample", _lhm_sample)

    return report


def _summary(report: dict) -> str:
    """Resume lisible en 5 lignes, imprime en plus du fichier JSON complet."""
    lines = []
    meta = report.get("meta", {})
    lines.append(f"Machine : {meta.get('hostname')} | admin={meta.get('is_admin')}")

    lg = report.get("list_gpus", {})
    if lg.get("ok") and lg.get("data"):
        for g in lg["data"]:
            lines.append(f"  GPU : {g.get('name')} ({g.get('vendor')}) "
                        f"via {g.get('source')} | temp={g.get('temp')} "
                        f"load={g.get('load')} clock={g.get('clock_sm_mhz')} "
                        f"power={g.get('power_w')}")
    elif lg.get("ok"):
        lines.append("  GPU : AUCUN detecte (ni NVML ni LHM)")
    else:
        lines.append(f"  GPU : ERREUR — {lg.get('error')}")

    tools = report.get("tools_dir", {})
    if tools.get("ok"):
        contents = tools["data"].get("active_dir_contents", [])
        has_lib = "LibreHardwareMonitorLib.dll" in contents
        lines.append(f"  tools/ actif : {tools['data'].get('active_dir')} "
                    f"({'DLL presente' if has_lib else 'DLL ABSENTE'})")
    else:
        lines.append(f"  tools/ : ERREUR — {tools.get('error')}")

    return "\n".join(lines)


def main() -> None:
    report = collect()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    host = report["meta"]["hostname"]
    out_path = _ROOT / f"ghisdiag_gpu_test_{host}_{ts}.txt"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    print("=" * 60)
    print(_summary(report))
    print("=" * 60)
    print(f"\nRapport complet ecrit : {out_path}")
    print("-> Renvoie ce fichier pour analyse.")


if __name__ == "__main__":
    main()
