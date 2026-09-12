"""
Ghisdiag - Orchestrateur
Exécute les collecteurs PowerShell et agrège les données.
"""

import subprocess
import json
import os
import re
import sys
import time
import logging
import threading
import concurrent.futures
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger(__name__)

COLLECTORS = [
    ("system_info",  "Système & Matériel",   "collectors/system_info.ps1",  120),
    ("performance",  "Performance",           "collectors/performance.ps1",  120),
    ("startup",      "Démarrage Windows",     "collectors/startup.ps1",      120),
    ("events",       "Événements Windows",    "collectors/events.ps1",       120),
    ("network",      "Réseau",                "collectors/network.ps1",      120),
    ("security",     "Sécurité",             "collectors/security.ps1",     120),
    ("software",     "Logiciels & Drivers",   "collectors/software.ps1",     120),
    ("smart",        "Santé disques (SMART)", "collectors/smart.ps1",         75),
]

VERSION = "2.2.0"
AUTHORS = "Ghislain DOUCY & Claude Code"

# Limite de taille de sortie d'un collecteur PowerShell (protection mémoire/DoS)
MAX_STDOUT_BYTES = 40 * 1024 * 1024   # 40 Mo
DEFAULT_TIMEOUT  = 120


def get_base_path() -> Path:
    """Répertoire de base — supporte PyInstaller --onefile."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).parent.resolve()


def _resolve_powershell() -> str:
    """Retourne le chemin absolu et vérifié de powershell.exe (évite le PATH hijacking)."""
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(sysroot) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if candidate.is_file():
        return str(candidate)
    # Fallback silencieux : laisse Windows résoudre via PATH
    return "powershell.exe"


_PS_EXE = _resolve_powershell()


def _validate_script_path(script_path: Path, base_path: Path) -> bool:
    """Vérifie que le script est sous base_path (protection path-traversal / symlink)."""
    try:
        resolved = script_path.resolve(strict=True)
        resolved.relative_to(base_path)
        return resolved.is_file() and resolved.suffix.lower() == ".ps1"
    except (ValueError, OSError):
        return False


# ── Passage d'arguments aux scripts PowerShell ──────────────────────────────
#
# On NE construit JAMAIS la ligne de commande avec les valeurs. Les anciennes
# versions faisaient `& 'script.ps1' -Name 'valeur'` en texte, avec deux trous :
#   - une valeur commençant par « - » était injectée sans guillemets ;
#   - l'échappement ne doublait que l'apostrophe ASCII, pas « ’ » / « ‘ » que
#     PowerShell traite aussi comme des guillemets.
# Un SSID, un nom d'imprimante ou un chemin bien choisi exécutait alors du code
# arbitraire dans le PowerShell élevé (démontré). Les mots de passe, eux,
# atterrissaient dans le journal Script Block Logging.
#
# Désormais : les arguments partent en JSON sur l'entrée standard, et le script
# est appelé par SPLATTING (`& $script @params`). Une valeur reste toujours une
# donnée, jamais du code — quels que soient ses caractères. Bénéfice au passage :
# un mot de passe commençant par « - » fonctionne enfin, et aucune valeur ne
# transite plus par la ligne de commande visible du processus.
_WRAPPER = (
    "$ErrorActionPreference='Stop'; "
    "[Console]::InputEncoding=[System.Text.Encoding]::UTF8; "
    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
    "$OutputEncoding=[System.Text.Encoding]::UTF8; "
    "$__in=[Console]::In.ReadToEnd()|ConvertFrom-Json; "
    "$__p=@{}; "
    "foreach($__e in $__in.args.PSObject.Properties){$__p[$__e.Name]=$__e.Value}; "
    "& $__in.script @__p"
)

# Cache nom de script -> {param_minuscule: est_un_switch}. Le bloc param() d'un
# collecteur ne change pas en cours d'exécution.
_PARAM_CACHE: dict[str, dict[str, bool]] = {}


def _script_params(script_path: Path) -> dict[str, bool]:
    """Paramètres déclarés par le bloc param() du script : nom (minuscule) -> switch ?

    Sert à valider les noms d'arguments fournis par l'appelant (on rejette un
    « -Nimporte ») et à savoir quels arguments sont des interrupteurs (sans
    valeur qui suit) plutôt que des paramètres à valeur.
    """
    key = str(script_path).lower()
    cached = _PARAM_CACHE.get(key)
    if cached is not None:
        return cached

    params: dict[str, bool] = {}
    try:
        text = script_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return params

    block = _extract_param_block(text)
    if block:
        # Chaque paramètre : d'éventuelles annotations `[...]` puis $Nom. Le type
        # `[switch]` (quelle que soit la casse) marque un interrupteur, qui n'a
        # pas de valeur qui le suit dans la liste d'arguments.
        for pm in re.finditer(r"((?:\[[^\]]*\]\s*)*)\$([A-Za-z_]\w*)", block):
            annotations = re.findall(r"\[([^\]]+)\]", pm.group(1))
            is_switch = any(a.strip().lower() == "switch" for a in annotations)
            params[pm.group(2).lower()] = is_switch
    _PARAM_CACHE[key] = params
    return params


def _extract_param_block(text: str) -> str:
    """Contenu du premier bloc param(...), parenthèses équilibrées.

    Une recherche naïve `\\(.*?\\)` s'arrête au premier « ) », or les
    annotations `[ValidateSet(...)]` / `[Parameter(...)]` en contiennent : le
    bloc était tronqué et les paramètres passaient inaperçus (validation
    désactivée en silence pour spooler_fix, entre autres)."""
    m = re.search(r"\bparam\s*\(", text, re.IGNORECASE)
    if not m:
        return ""
    depth = 0
    start = m.end()
    for i in range(m.end() - 1, len(text)):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start:i]
    return ""


def _build_ps_args(script_path: Path, extra_args: list) -> dict:
    """Transforme la liste plate [-Nom, valeur, -Interrupteur, …] en dict de
    splatting {Nom: valeur/True}, en validant chaque nom contre le script.

    Lève ValueError sur un nom de paramètre inconnu ou une valeur orpheline :
    une faute de frappe d'appelant ne doit pas passer en silence.
    """
    declared = _script_params(script_path)
    result: dict[str, object] = {}
    i = 0
    n = len(extra_args)
    while i < n:
        token = extra_args[i]
        if not isinstance(token, str) or not token.startswith("-"):
            raise ValueError(f"Argument inattendu (nom de paramètre attendu) : {token!r}")
        name = token[1:]
        key = name.lower()
        if declared and key not in declared:
            raise ValueError(f"Paramètre inconnu pour {script_path.name} : -{name}")
        if declared.get(key, False):
            result[name] = True          # interrupteur : pas de valeur qui suit
            i += 1
        else:
            if i + 1 >= n:
                raise ValueError(f"Valeur manquante pour -{name}")
            result[name] = extra_args[i + 1]   # valeur telle quelle, même « -x »
            i += 2
    return result


def _ps_argv(ps_exe: str) -> list:
    return [ps_exe, "-NonInteractive", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-Command", _WRAPPER]


def _ps_payload(script_path: Path, args: dict) -> bytes:
    """JSON envoyé sur stdin : chemin du script + arguments. ASCII strict pour
    ne dépendre d'aucun réglage de page de code du tuyau."""
    return json.dumps(
        {"script": str(script_path), "args": args},
        ensure_ascii=True,
    ).encode("ascii")


def run_collector(name: str, script_path: Path, base_path: Path,
                  timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Exécute un script PowerShell et retourne les données JSON parsées."""
    start = time.time()

    if not _validate_script_path(script_path, base_path):
        return {"collector": name, "status": "invalid_path",
                "error": "Chemin de script invalide ou hors du répertoire de base"}

    try:
        # Force UTF-8 en sortie PowerShell (PS 5.1 utilise CP850/OEM par défaut
        # sur Windows français, ce qui corrompt les accents dans le JSON).
        escaped_path = str(script_path.resolve()).replace("'", "''")
        ps_cmd = (
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
            "$OutputEncoding=[System.Text.Encoding]::UTF8; "
            f"& '{escaped_path}'"
        )

        result = subprocess.run(
            [
                _PS_EXE,
                "-NonInteractive",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-Command", ps_cmd,
            ],
            capture_output=True,
            timeout=timeout,
            shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        elapsed = round(time.time() - start, 2)

        # Protection : rejeter les sorties monstrueuses
        if len(result.stdout) > MAX_STDOUT_BYTES:
            return {"collector": name, "status": "too_large",
                    "error": f"Sortie du script > {MAX_STDOUT_BYTES // (1024*1024)} Mo",
                    "elapsed_sec": elapsed}

        stdout = result.stdout.decode("utf-8", errors="replace").strip()
        stderr = result.stderr.decode("utf-8", errors="replace").strip()

        if result.returncode != 0 and not stdout:
            return {"collector": name, "status": "error",
                    "error": (stderr[:500] or "Exit code non nul"),
                    "elapsed_sec": elapsed}

        if not stdout:
            return {"collector": name, "status": "empty",
                    "error": "Aucune sortie du script", "elapsed_sec": elapsed}

        data = json.loads(stdout)
        if not isinstance(data, dict):
            return {"collector": name, "status": "bad_format",
                    "error": "Le collecteur n'a pas retourné un objet JSON",
                    "elapsed_sec": elapsed}

        data["_status"]      = "ok"
        data["_elapsed_sec"] = elapsed
        return data

    except subprocess.TimeoutExpired:
        return {"collector": name, "status": "timeout",
                "error": f"Timeout après {timeout}s"}
    except json.JSONDecodeError as e:
        return {"collector": name, "status": "json_error",
                "error": f"{e.msg} (ligne {e.lineno})"}
    except OSError as e:
        return {"collector": name, "status": "os_error", "error": str(e)}
    except Exception as e:
        logger.exception("Erreur inattendue dans run_collector(%s)", name)
        return {"collector": name, "status": "exception", "error": str(e)}


def run_ps_action(script_rel: str, extra_args: list[str], timeout: int = 60) -> dict:
    """Exécute un script PowerShell de dépannage et retourne le JSON parsé.

    Les arguments passent en JSON sur stdin, jamais dans la ligne de commande
    (voir _WRAPPER) : une valeur reste une donnée, pas du code injectable."""
    base     = get_base_path()
    script_p = (base / script_rel).resolve()

    if not _validate_script_path(script_p, base):
        raise RuntimeError(f"Chemin de script invalide : {script_rel}")

    ps_args = _build_ps_args(script_p, extra_args)
    payload = _ps_payload(script_p, ps_args)

    result = subprocess.run(
        _ps_argv(_PS_EXE),
        input=payload,
        capture_output=True,
        timeout=timeout,
        shell=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    stdout = result.stdout.decode("utf-8", errors="replace").strip()
    if not stdout:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()[:500]
        raise RuntimeError(f"Pas de sortie du script. Stderr : {stderr}")

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"JSON invalide : {e}\nSortie : {stdout[:300]}")


def run_ps_stream(script_rel: str, extra_args: list[str], on_line, timeout: int = 900) -> int:
    """Exécute un script PS1 et appelle on_line(text) pour chaque ligne stdout (streaming)."""
    base     = get_base_path()
    script_p = (base / script_rel).resolve()

    if not _validate_script_path(script_p, base):
        raise RuntimeError(f"Chemin de script invalide : {script_rel}")

    ps_args = _build_ps_args(script_p, extra_args)
    payload = _ps_payload(script_p, ps_args)

    proc = subprocess.Popen(
        _ps_argv(_PS_EXE),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        shell=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    # Écrire le JSON puis fermer stdin : le wrapper attend un ReadToEnd(). Sans
    # cette fermeture, le script bloquerait indéfiniment.
    try:
        proc.stdin.write(payload)
        proc.stdin.close()
    except OSError:
        pass
    try:
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if line.strip():
                on_line(line)
    finally:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
    return proc.returncode


class DiagnosticOrchestrator:
    def __init__(self, progress_callback: Optional[Callable] = None):
        self.base_path       = get_base_path()
        self.progress_cb     = progress_callback or (lambda *a, **kw: None)
        self.results         = {}
        self.collection_time = None
        self.machine_name    = os.environ.get("COMPUTERNAME", "UNKNOWN")

    def _notify(self, step: str, current: int, total: int, status: str = "running",
                elapsed: float = 0, ps_errors: list = None):
        self.progress_cb(step=step, current=current, total=total, status=status,
                         elapsed=elapsed, ps_errors=ps_errors or [])

    def run(self) -> dict:
        """Lance tous les collecteurs en parallèle et retourne les données agrégées."""
        total      = len(COLLECTORS)
        self.results = {}
        start_time = datetime.now()
        lock       = threading.Lock()
        completed  = 0

        self._notify("Lancement des collecteurs…", 0, total)

        # Résolution préalable des chemins (séquentielle, triviale)
        missing = {}
        runnable = []
        for name, label, rel_path, timeout in COLLECTORS:
            script_path = self.base_path / rel_path
            if not script_path.exists():
                logger.warning("Script introuvable : %s", script_path)
                missing[name] = {
                    "collector": name,
                    "status":    "missing",
                    "error":     f"Script introuvable : {rel_path}",
                }
            else:
                runnable.append((name, label, script_path, timeout))

        self.results.update(missing)

        max_workers = min(4, len(runnable)) if runnable else 1
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(run_collector, name, script_path, self.base_path, timeout): (name, label)
                for name, label, script_path, timeout in runnable
            }
            logger.info(">>> %d collecteurs lancés en parallèle (workers=%d)",
                        len(runnable), max_workers)

            for future in concurrent.futures.as_completed(future_map):
                name, label = future_map[future]
                data = future.result()

                with lock:
                    self.results[name] = data
                    completed += 1
                    current = completed

                elapsed  = data.get("_elapsed_sec", 0)
                ps_errs  = data.get("collector_errors") or []
                ps_times = data.get("collector_timings") or {}

                if data.get("_status") != "ok":
                    logger.warning("<<< Collecteur [%s] ECHEC (%.1fs) — statut=%s — %s",
                                   name, elapsed, data.get("status"), data.get("error", ""))
                    self._notify(f"Échec : {label}", current, total,
                                 status="error", elapsed=elapsed,
                                 ps_errors=[f"statut={data.get('status')} — {data.get('error','')}"])
                else:
                    logger.info("<<< Collecteur [%s] OK (%.1fs)", name, elapsed)
                    if ps_times:
                        detail = ", ".join(f"{k}={v}s" for k, v in ps_times.items())
                        logger.info("    Timings internes [%s] : %s", name, detail)

                    ps_notes = data.get("collector_notes") or []
                    if ps_notes:
                        logger.debug("    Notes [%s] : %s", name, "; ".join(ps_notes))

                    notify_status = "warn" if ps_errs else "running"
                    self._notify(f"✓ {label}  ({elapsed:.1f}s)", current, total,
                                 status=notify_status, elapsed=elapsed, ps_errors=ps_errs)

        # Sonde << sante capteurs >> (cote Python : PawnIO + LibreHardwareMonitor)
        # ajoutee au rapport pour expliquer une temperature CPU absente plutot
        # que de la laisser muette. Best-effort : un echec ne bloque rien.
        try:
            from collectors import sensors_health
            self.results["sensors"] = sensors_health.collect()
        except Exception as exc:
            logger.debug("Sonde sante capteurs : %s", exc)
            self.results["sensors"] = {"_status": "error", "error": str(exc)}

        self.collection_time = datetime.now()
        elapsed_total = round((self.collection_time - start_time).total_seconds(), 1)

        self._notify("Finalisation du rapport…", total, total, status="done")

        return self._build_report(start_time, elapsed_total)

    def _build_report(self, start_time: datetime, elapsed_total: float) -> dict:
        """Construit le rapport agrégé final."""
        failed = [
            name for name, data in self.results.items()
            if data.get("_status") != "ok"
        ]

        return {
            "meta": {
                "version":         VERSION,
                "authors":         AUTHORS,
                "tool":            "Ghisdiag",
                "machine":         self.machine_name,
                "collected_at":    self.collection_time.strftime("%Y-%m-%d %H:%M:%S"),
                "started_at":      start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "elapsed_sec":     elapsed_total,
                "collectors_ok":   len(COLLECTORS) - len(failed),
                "collectors_fail": failed,
            },
            "data": self.results,
        }
