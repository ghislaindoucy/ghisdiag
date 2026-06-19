"""
Ghisdiag - Generateur de charge CPU (bench thermique)

Lance N processus enfants (par defaut un par processeur logique) executant une
boucle de calcul intensif. Sert a chauffer le CPU de maniere reproductible
et saturee (100% utilisation) pendant la phase de charge du bench thermique.

Terminer le processus parent force l'arret : les enfants sont tues via
multiprocessing.

Utilise multiprocessing plutot que PowerShell pour :
- Meilleure saturation CPU (pas de GIL, calcul pur)
- Algos de calcul plus intensifs (pas de surcharge PowerShell)
- Meilleure portabilite
"""

import math
import multiprocessing as mp
import signal
import sys
import time
from typing import Optional


def _cpu_worker(intensity: int, deadline: float) -> None:
    """Worker thread : boucle de calcul intensif jusqu'a deadline (time.time()).

    intensity: ratio cyclique (1..100). 100 = aucune pause.
    deadline: timestamp Unix absolu de fin.
    """
    # Ignore SIGTERM dans les enfants : le parent les tue directement.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

    work_ratio = intensity / 100.0
    cycle_duration = 0.05  # 50 ms par cycle
    work_duration = cycle_duration * work_ratio
    pause_duration = cycle_duration * (1 - work_ratio)

    while time.time() < deadline:
        # Travail : boucle de calculs flottants intensifs.
        # Suffisamment complexe pour eviter l'optimisation du JIT.
        t_start = time.time()
        while time.time() - t_start < work_duration:
            # Chaîne intensive de calculs FPU : plus de travail = CPU sature.
            x = y = z = 1.0
            for _ in range(1000):
                # Calculs flottants multiples (ALU + FPU).
                x = math.sqrt(abs(x * 1.001 + 0.1)) + math.sin(x) * 0.1
                y = math.cos(y * 0.999 - 0.2) * math.sqrt(abs(y))
                z = math.sqrt(abs(z * 1.0002 + 0.05))

                # Borner pour eviter l'overflow.
                if x > 1e8 or x < -1e8:
                    x = 1.0
                if y > 1e8 or y < -1e8:
                    y = 1.0
                if z > 1e8 or z < -1e8:
                    z = 1.0

        # Pause (si intensite < 100).
        if pause_duration > 0.001:
            time.sleep(pause_duration)


def main() -> None:
    """Lance N workers jusqu'a signal de terminaison (SIGTERM / parent mort)."""
    parser = __import__("argparse").ArgumentParser(
        description="CPU load generator for thermal benchmarking"
    )
    parser.add_argument("--threads", type=int, default=0,
                        help="Number of worker threads (0=all logical CPUs)")
    parser.add_argument("--intensity", type=int, default=100,
                        help="CPU load intensity (1..100)")
    parser.add_argument("--duration", type=int, default=0,
                        help="Max duration in seconds (0=infinite, parent termination)")

    args = parser.parse_args()

    threads = args.threads if args.threads > 0 else mp.cpu_count()
    intensity = max(1, min(100, args.intensity))
    duration = args.duration

    deadline = time.time() + duration if duration > 0 else float("inf")

    # Lance les workers en processus separes.
    processes = []
    try:
        for _ in range(threads):
            p = mp.Process(target=_cpu_worker, args=(intensity, deadline), daemon=False)
            p.start()
            processes.append(p)

        # Attend la fin (deadline ou terminaison externe).
        for p in processes:
            p.join(timeout=max(0, deadline - time.time() + 1))

    except KeyboardInterrupt:
        pass

    finally:
        # Nettoie les processus encore en cours.
        for p in processes:
            if p.is_alive():
                p.terminate()
        for p in processes:
            p.join(timeout=1)
            if p.is_alive():
                p.kill()
            p.close()


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)  # coherent sur toutes les plateformes
    main()
