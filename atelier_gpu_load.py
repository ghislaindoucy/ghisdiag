"""
Ghisdiag - Test de terrain du GENERATEUR DE CHARGE GPU (chantier M2).

Deroulement automatique, ~45 s :
  1. enumere les adaptateurs (DXGI) et choisit le GPU a chauffer (dGPU le plus
     gros, ou l'iGPU s'il n'y a que lui) ;
  2. mesure la temperature AU REPOS (baseline) ;
  3. lance la charge GPU (D3D11 compute) 30 s en interne ;
  4. echantillonne temp / charge / power pendant la chauffe ;
  5. laisse redescendre quelques secondes, puis ecrit un rapport JSON + un
     verdict lisible a cote de ce script (sur la cle USB).

Objectif : verifier sur Intel / AMD que la charge MONTE la temperature, SANS
TDR (reset du pilote / ecran noir) ni plantage. Sur un iGPU (pas de capteur de
temperature GPU), on regarde la temperature du PACKAGE CPU, que l'iGPU chauffe.

ATTENTION : chauffer le GPU qui pilote l'ecran peut le rendre saccade ~30 s.
C'est normal. Ne rien faire de lourd pendant le test.

Usage : py atelier_gpu_load.py   (ou double-clic sur test_charge_gpu_atelier.bat)
"""

import ctypes
import json
import socket
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(_ROOT))

DURATION = 30          # duree de charge (s)
SAMPLE_EVERY = 3.0     # periode d'echantillonnage (s)


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _sample() -> dict:
    """Un echantillon capteurs (tous vendors) via LHM : temp/charge/clock/power
    GPU + temperature package CPU (utile pour les iGPU sans temp GPU)."""
    try:
        from collectors import sensors
        s = sensors.read_once(timeout=20) or {}
    except Exception:
        s = {}
    return {
        "gpu_temp":  s.get("gpu_temp"),
        "gpu_load":  s.get("gpu_load"),
        "gpu_clock": s.get("gpu_core_clock"),
        "gpu_power": s.get("gpu_power"),
        "cpu_temp":  s.get("cpu_ref"),
    }


def _fmt(sm: dict) -> str:
    return (f"GPU {sm['gpu_temp']}C / {sm['gpu_load']}% / {sm['gpu_clock']}MHz / "
            f"{sm['gpu_power']}W   CPU {sm['cpu_temp']}C")


def _peak(samples: list, key: str):
    vals = [s[key] for s in samples if s.get(key) is not None]
    return max(vals) if vals else None


def main() -> None:
    report: dict = {
        "meta": {
            "hostname": socket.gethostname(),
            "is_admin": _is_admin(),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "duration_s": DURATION,
        },
        "adapters": [], "target": None, "available": False,
        "baseline": [], "load": [], "cooldown": [],
        "error": None, "tdr_or_crash": None,
    }

    try:
        from collectors import gpu_load
    except Exception as exc:
        report["error"] = f"import gpu_load: {exc}"
        _finish(report)
        return

    report["available"] = gpu_load.available()
    if not report["available"]:
        report["error"] = "D3D11 / DXGI / d3dcompiler_47.dll indisponibles."
        _finish(report)
        return

    adapters = gpu_load.list_adapters()
    report["adapters"] = adapters
    print(f"{len(adapters)} adaptateur(s) :")
    for a in adapters:
        tag = " [LOGICIEL]" if a["is_software"] else ""
        print(f"  [{a['index']}] {a['name']} ({a['vendor']}) {a['vram_mb']} Mo{tag}")

    info = gpu_load._match_adapter(adapters, None)
    if info is None:
        report["error"] = "Aucun adaptateur MATERIEL utilisable (que du logiciel/WARP)."
        _finish(report)
        return
    report["target"] = info
    print(f"\nCible de chauffe : [{info['index']}] {info['name']} ({info['vendor']})")

    # 1) Baseline au repos
    print("\nMesure au repos (5 s)...")
    for _ in range(2):
        sm = _sample()
        report["baseline"].append(sm)
        print("  repos  :", _fmt(sm))
        time.sleep(2)

    # 2) Charge en thread, echantillonnage dans le thread principal
    load = gpu_load.GpuLoad()
    stop = threading.Event()
    err: dict = {}

    def _run():
        try:
            if not load.setup(info):
                err["setup"] = "echec setup (device/shader)"
                return
            load.run(100, DURATION + 5, cancel=lambda: stop.is_set())
        except Exception as exc:
            err["exc"] = f"{type(exc).__name__}: {exc}"
            err["tb"] = traceback.format_exc()

    print(f"\n>>> CHARGE GPU {DURATION}s (l'ecran peut saccader, c'est normal)\n")
    th = threading.Thread(target=_run, daemon=True)
    th.start()

    t0 = time.monotonic()
    while time.monotonic() - t0 < DURATION:
        sm = _sample()
        sm["t"] = round(time.monotonic() - t0, 1)
        report["load"].append(sm)
        print(f"  t+{sm['t']:4.0f}s :", _fmt(sm))
        if err:
            break
        time.sleep(SAMPLE_EVERY)

    stop.set()
    th.join(timeout=10)
    try:
        load.close()
    except Exception:
        pass

    if err:
        report["tdr_or_crash"] = err
        print("\n[!] Le worker de charge a signale une erreur :", err.get("setup") or err.get("exc"))

    # 3) Redescente
    print("\nRedescente (6 s)...")
    for _ in range(2):
        time.sleep(3)
        sm = _sample()
        report["cooldown"].append(sm)
        print("  apres  :", _fmt(sm))

    _finish(report)


def _finish(report: dict) -> None:
    # Verdict
    base_gpu = _peak(report["baseline"], "gpu_temp")
    peak_gpu = _peak(report["load"], "gpu_temp")
    base_cpu = _peak(report["baseline"], "cpu_temp")
    peak_cpu = _peak(report["load"], "cpu_temp")
    peak_load = _peak(report["load"], "gpu_load")

    verdict = []
    if report.get("error"):
        verdict.append("ECHEC : " + report["error"])
    elif report.get("tdr_or_crash"):
        verdict.append("PROBLEME : le worker de charge a echoue (voir tdr_or_crash).")
    else:
        if base_gpu is not None and peak_gpu is not None:
            verdict.append(f"GPU : {base_gpu}C au repos -> {peak_gpu}C en charge "
                          f"(delta {round(peak_gpu - base_gpu, 1)}C)")
        if peak_load is not None:
            verdict.append(f"Charge GPU max vue : {peak_load}%")
        if base_cpu is not None and peak_cpu is not None:
            verdict.append(f"CPU package : {base_cpu}C -> {peak_cpu}C "
                          f"(pertinent si iGPU sans temp GPU)")
        if peak_gpu is None and base_gpu is None:
            verdict.append("Pas de temperature GPU (probablement iGPU) : "
                          "regarder la temperature CPU package ci-dessus.")

    report["verdict"] = verdict

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    host = report["meta"]["hostname"]
    out = _ROOT / f"ghisdiag_charge_gpu_{host}_{ts}.txt"
    try:
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    except Exception as exc:
        print("Ecriture du rapport impossible :", exc)
        out = None

    print("\n" + "=" * 60)
    for line in verdict:
        print(" " + line)
    print("=" * 60)
    if out:
        print(f"\nRapport complet ecrit : {out}")
        print("-> Renvoie ce fichier pour analyse.")


if __name__ == "__main__":
    main()
