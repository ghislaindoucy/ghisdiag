"""
Ghisdiag - Test de terrain du MOTEUR DE BENCH THERMIQUE GENERALISE (chantier M3).

Contrairement a atelier_gpu_load.py (qui pilote directement le generateur de
charge D3D11), ce script pilote le MOTEUR COMPLET via
thermal_bench.ThermalBench(BenchConfig(target="gpu")) : resolution
d'adaptateur DXGI, session NVML persistante, generateur de charge en
sous-processus (worker), surveillance d'urgence (temp + throttle NVML),
calcul des metriques GPU, sauvegarde JSON. C'est exactement le chemin que
prendra l'UI (M4) une fois branchee.

Deroulement automatique, ~2 min :
  1. repos 15 s (baseline) ;
  2. charge GPU 60 s (D3D11 compute, intensite 100%) ;
  3. refroidissement 30 s ;
  4. verdict + copie du rapport a cote de ce script (sur la cle USB).

Objectif atelier : confirmer que le moteur GENERALISE fonctionne de bout en
bout sur du materiel reel (pas seulement les fakes des tests unitaires) —
resolution d'adaptateur correcte, echantillons GPU coherents (clock NVML si
NVIDIA, sinon LHM), pas de faux declenchement d'urgence, session JSON valide.

ATTENTION : chauffe le GPU qui pilote l'ecran -> peut saccader ~60 s. Normal.

Usage : py atelier_thermal_bench_gpu.py   (ou double-clic sur
        test_thermal_bench_gpu_atelier.bat)
"""

import ctypes
import json
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(_ROOT))

IDLE_SEC     = 15
LOAD_SEC     = 60
COOLDOWN_SEC = 30


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def main() -> None:
    report: dict = {
        "meta": {
            "hostname":  socket.gethostname(),
            "is_admin":  _is_admin(),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "protocol":  {"idle_sec": IDLE_SEC, "load_sec": LOAD_SEC,
                         "cooldown_sec": COOLDOWN_SEC},
        },
        "session": None, "session_path": None,
        "sample_count": 0, "phases_seen": [],
        "error": None,
    }

    try:
        from thermal_bench import BenchConfig, ThermalBench
    except Exception as exc:
        report["error"] = f"import thermal_bench : {exc}"
        _finish(report)
        return

    cfg = BenchConfig(
        label="libre", target="gpu",
        idle_sec=IDLE_SEC, load_sec=LOAD_SEC, cooldown_sec=COOLDOWN_SEC,
        intensity=100, sample_interval_ms=2000,
        output_dir=str(_ROOT),   # rapport JSON standard a cote du script
    )

    done = threading.Event()
    result: dict = {"session": None, "path": None, "error": None}
    phases_seen: list[str] = []
    t0 = time.monotonic()

    def on_phase(phase, idx, total):
        phases_seen.append(phase.value)
        print(f"\n>>> Phase {idx}/{total} : {phase.value.upper()} "
              f"(t+{time.monotonic() - t0:.0f}s)")

    def on_sample(rec):
        report["sample_count"] += 1
        bits = [f"t+{rec['t']:5.1f}s", rec["phase"]]
        if rec.get("gpu") is not None:
            bits.append(f"GPU {rec['gpu']}C")
        if rec.get("gpu_load") is not None:
            bits.append(f"{rec['gpu_load']}%")
        if rec.get("gpu_clock") is not None:
            bits.append(f"{rec['gpu_clock']}MHz")
        if rec.get("gpu_power") is not None:
            bits.append(f"{rec['gpu_power']}W")
        if rec.get("gpu_throttle"):
            bits.append(f"throttle={rec['gpu_throttle']}")
        print("  " + "  ".join(str(b) for b in bits))

    def on_finish(session, path):
        result["session"] = session
        result["path"] = str(path) if path else None
        done.set()

    def on_error(msg):
        result["error"] = msg
        done.set()

    print(f"Protocole : repos {IDLE_SEC}s -> charge GPU {LOAD_SEC}s "
          f"(100%) -> refroidissement {COOLDOWN_SEC}s")
    print("(l'ecran peut saccader pendant la charge, c'est normal)\n")

    bench = ThermalBench(cfg, on_sample=on_sample, on_phase=on_phase,
                         on_finish=on_finish, on_error=on_error)
    if not bench.start():
        report["error"] = "ThermalBench.start() a refuse (voir logs console)."
        _finish(report)
        return

    # Marge large : protocole + demarrage NVML/D3D11 + temps de reaction.
    timeout = IDLE_SEC + LOAD_SEC + COOLDOWN_SEC + 60
    if not done.wait(timeout=timeout):
        report["error"] = f"Timeout : le bench n'a pas termine en {timeout}s."
        bench.stop()
        bench.join(timeout=10)
        _finish(report)
        return
    bench.join(timeout=10)

    report["phases_seen"] = phases_seen
    report["session"] = result["session"]
    report["session_path"] = result["path"]
    if result["error"]:
        report["error"] = result["error"]

    _finish(report)


def _finish(report: dict) -> None:
    verdict = []
    session = report.get("session")

    if report.get("error"):
        verdict.append("ECHEC : " + report["error"])
    elif session is None:
        verdict.append("ECHEC : aucune session produite (voir error).")
    else:
        gpu_adapter = session.get("gpu_adapter") or {}
        m = session.get("metrics") or {}
        verdict.append(f"Adaptateur cible : {gpu_adapter.get('name', '?')} "
                       f"({gpu_adapter.get('vendor', '?')})")
        verdict.append(f"Echantillons collectes : {report['sample_count']} "
                       f"- phases vues : {', '.join(report['phases_seen']) or 'aucune'}")
        if session.get("aborted"):
            verdict.append(f"ABANDONNE : {session.get('abort_reason')}")
        if session.get("emergency"):
            verdict.append("URGENCE DECLENCHEE pendant la charge "
                          "(voir samples pour la raison - a examiner).")
        if m.get("gpu_idle_c") is not None and m.get("gpu_max_c") is not None:
            verdict.append(f"GPU : {m['gpu_idle_c']}C au repos -> "
                          f"{m['gpu_max_c']}C max en charge "
                          f"(delta {m.get('gpu_delta_c')}C)")
        if m.get("gpu_clock_max_mhz") is not None:
            verdict.append(f"Clock GPU max (source NVML si NVIDIA) : "
                          f"{m['gpu_clock_max_mhz']} MHz "
                          f"(chute {m.get('gpu_clock_drop_pct')}%)")
        if m.get("gpu_power_max_w") is not None:
            verdict.append(f"Power GPU max : {m['gpu_power_max_w']} W")
        if m.get("gpu_throttling"):
            verdict.append("THROTTLING THERMIQUE detecte (confirme par NVML).")
        if m.get("gpu_power_limited"):
            verdict.append("Limite de PUISSANCE detectee (normal, pas un souci "
                          "de refroidissement).")
        if m.get("gpu_idle_c") is None:
            verdict.append("Pas de temperature GPU dans les metriques : "
                          "GPU probablement non benchable (iGPU).")
        if not session.get("aborted") and not session.get("emergency"):
            verdict.append("Bench termine normalement, sans urgence ni abandon.")

    report["verdict"] = verdict

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    host = report["meta"]["hostname"]
    out = _ROOT / f"ghisdiag_thermal_bench_gpu_{host}_{ts}.txt"
    try:
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                  default=str),
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
    if report.get("session_path"):
        print(f"Session bench (format standard) : {report['session_path']}")


if __name__ == "__main__":
    main()
