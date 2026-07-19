"""
Ghisdiag - Résumé exécutif « Ce qui ralentit ce PC »

Moteur de règles pur (aucun HTML) : à partir des données collectées, produit une
liste de « freins » priorisés par impact perçu sur les performances. Le générateur
de rapport n'en fait que le rendu (top 3), et la liste complète est embarquée dans
le JSON (clé `executive_summary`) pour l'audit IA et le futur historique.

Chaque finding est un dict :
    key      identifiant stable de la règle (pour tests / historique)
    score    impact perf estimé 0-100 (tri décroissant)
    severity "crit" (>=70) | "warn" (>=50) | "info"
    title    le frein, en une phrase courte
    constat  ce qu'on a mesuré, chiffré
    action   ce que le technicien peut proposer

Garde-fous honnêteté (ligne de conduite du projet) :
- pas de verdict fort quand la donnée ne permet pas de l'affirmer (ex. disque
  mécanique présent mais un SSD aussi → Windows est peut-être sur le SSD) ;
- les mesures instantanées (CPU/RAM à l'instant T) sont formulées comme telles.
"""

from collections import Counter

# Seuil « démarrage lent » : l'ID 100 est journalisé à CHAQUE boot, on ne retient
# que les durées anormales (même seuil que les alertes du rapport).
SLOW_BOOT_MS = 60_000
# Nombre de programmes au démarrage à partir duquel on parle d'encombrement.
STARTUP_BLOAT_MIN = 12


# ── Accès sécurisé (copies locales pour rester sans dépendance au générateur) ──

def _v(data, *keys, default=None):
    for k in keys:
        if not isinstance(data, dict):
            return default
        data = data.get(k, default)
        if data is default:
            return default
    return data if data is not None else default


def _lst(val):
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        return [val] if val else []
    return []


def _dicts(val):
    return [x for x in _lst(val) if isinstance(x, dict)]


def _num(val):
    return val if isinstance(val, (int, float)) and not isinstance(val, bool) else None


def _severity(score: int) -> str:
    return "crit" if score >= 70 else ("warn" if score >= 50 else "info")


def _finding(key, score, title, constat, action):
    return {
        "key": key, "score": score, "severity": _severity(score),
        "title": title, "constat": constat, "action": action,
    }


# ── Règles ────────────────────────────────────────────────────────────────────

def _rule_hdd(data, out):
    """Disque mécanique : frein n°1 classique. Verdict fort seulement si c'est le
    seul disque interne ; sinon Windows est peut-être sur le SSD → conditionnel."""
    if _v(data, "system_info", "_status") != "ok":
        return
    physical = _dicts(_v(data, "system_info", "disks", "physical"))
    internal = [d for d in physical if (d.get("interface") or "").upper() != "USB"]
    if not internal:
        return
    hdds   = [d for d in internal if str(d.get("media_type") or "").upper() == "HDD"]
    others = [d for d in internal if d not in hdds]
    if not hdds:
        return
    models = ", ".join(str(d.get("model") or "disque") for d in hdds)
    if not others:
        out.append(_finding(
            "hdd_system", 90,
            "Windows tourne sur un disque dur mécanique",
            f"Seul disque interne détecté : {models}. Un disque mécanique plafonne "
            "tout le système (démarrage, ouverture des applications, mises à jour).",
            "Remplacer par un SSD (clonage possible) — c'est l'intervention au "
            "meilleur rapport gain/prix sur cette machine.",
        ))
    else:
        out.append(_finding(
            "hdd_present", 40,
            "Un disque mécanique est présent",
            f"{models} — un SSD est aussi présent, Windows est probablement dessus. "
            "Si des données actives (profil, jeux, logiciels) sont sur le disque "
            "mécanique, elles restent lentes.",
            "Vérifier quel disque héberge Windows et les données les plus utilisées.",
        ))


def _rule_ram(data, out):
    """RAM : quantité d'abord (structurel), saturation ensuite (instantané)."""
    total = _num(_v(data, "system_info", "ram", "total_gb"))
    usage = _num(_v(data, "performance", "ram", "usage_percent"))
    if usage is None:
        usage = _num(_v(data, "system_info", "ram", "usage_percent"))

    top = _dicts(_v(data, "performance", "ram", "top_processes"))
    top_str = ""
    if top:
        p = top[0]
        if p.get("name") and _num(p.get("ram_mb")):
            top_str = f" Premier consommateur : {p['name']} ({round(p['ram_mb'])} Mo)."

    if total is not None and total <= 4.5:
        constat = f"{round(total)} Go de RAM au total"
        if usage is not None:
            constat += f", utilisée à {usage}% au moment du diagnostic"
        out.append(_finding(
            "ram_insufficient", 85,
            "Mémoire vive insuffisante (4 Go ou moins)",
            constat + ". En dessous de 8 Go, Windows compense en écrivant sur le "
                      "disque (swap), ce qui ralentit tout." + top_str,
            "Étendre la RAM (8 Go minimum recommandé) si la carte mère le permet.",
        ))
        return

    if usage is not None and usage >= 90:
        constat = f"RAM utilisée à {usage}% au moment du diagnostic"
        if total is not None:
            constat += f" (sur {round(total)} Go)"
        out.append(_finding(
            "ram_saturated", 75,
            "Mémoire vive saturée",
            constat + ". À ce niveau, Windows swappe sur le disque et tout se fige "
                      "par à-coups." + top_str,
            "Identifier le processus gourmand (fuite, malware, trop d'onglets ?) "
            "ou étendre la RAM si l'usage est légitime.",
        ))
    elif (total is not None and total <= 8.5
          and usage is not None and usage >= 85):
        out.append(_finding(
            "ram_tight", 60,
            "Mémoire vive à l'étroit",
            f"{round(total)} Go de RAM utilisés à {usage}% au moment du diagnostic."
            + top_str,
            "Surveiller à l'usage réel ; une extension mémoire est à envisager.",
        ))


def _rule_disk_full(data, out):
    """Volume système presque plein : Windows a besoin de marge pour respirer."""
    if _v(data, "system_info", "_status") != "ok":
        return
    for vol in _dicts(_v(data, "system_info", "disks", "volumes")):
        letter = str(vol.get("drive_letter") or "")
        if not letter.upper().startswith("C"):
            continue
        free = _num(vol.get("free_gb"))
        pct  = _num(vol.get("used_percent"))
        if vol.get("low_space") or (pct is not None and pct >= 90):
            out.append(_finding(
                "disk_system_full", 78,
                "Disque système presque plein",
                f"{letter} : {free if free is not None else '?'} Go libres "
                f"({pct if pct is not None else '?'}% utilisé). Sans espace libre, "
                "Windows Update échoue, le swap et les fichiers temporaires étouffent.",
                "Libérer de l'espace (nettoyage de disque, déplacer photos/vidéos, "
                "désinstaller l'inutile) — viser au moins 15-20% libres.",
            ))
        return  # un seul volume C:


def _rule_disk_failing(data, out):
    """Disque en souffrance : un disque qui meurt fige la machine (retries E/S)
    en plus du risque de perte de données."""
    smart = data.get("smart") or {}
    failing = []
    if smart.get("_status") == "ok" and smart.get("available"):
        for d in _dicts(smart.get("disks")):
            if d.get("smart_passed") is False:
                failing.append(str(d.get("model") or d.get("device") or "disque"))
    if failing:
        out.append(_finding(
            "disk_failing", 88,
            "Un disque est en fin de vie",
            f"SMART en échec : {', '.join(failing)}. Les secteurs défaillants "
            "provoquent des gels et des lenteurs erratiques — et une perte de "
            "données est possible à tout moment.",
            "Sauvegarder immédiatement, puis remplacer le disque.",
        ))
        return

    ev = data.get("events") or {}
    if not isinstance(ev, dict) or ev.get("_status") not in ("ok", None):
        return
    disk_ev = _dicts(ev.get("disk_events"))
    ntfs_ev = _dicts(ev.get("ntfs_events"))
    if disk_ev:
        extra = f" et {len(ntfs_ev)} erreur(s) NTFS" if ntfs_ev else ""
        out.append(_finding(
            "disk_io_errors", 72,
            "Erreurs disque détectées",
            f"{len(disk_ev)} erreur(s) d'entrée/sortie{extra} sur 14 jours. Chaque "
            "erreur se paie en nouvelles tentatives : gels et lenteurs erratiques.",
            "Vérifier le disque (SMART ci-dessous, chkdsk /f) et sauvegarder.",
        ))


def _rule_slow_boot(data, out):
    """Démarrage lent mesuré par Windows (Diagnostics-Performance ID 100),
    avec les applications responsables (ID 101) si identifiées."""
    ev = data.get("events") or {}
    if not isinstance(ev, dict) or ev.get("_status") not in ("ok", None):
        return
    diag = _dicts(ev.get("diag_perf"))
    slow = [
        e for e in diag
        if e.get("category") == "boot"
        and _num(e.get("duration_ms")) is not None
        and e["duration_ms"] >= SLOW_BOOT_MS
    ]
    if not slow:
        return
    worst = max(e["duration_ms"] for e in slow)
    culprits = Counter(
        e["app_name"] for e in diag
        if e.get("category") == "boot-app" and e.get("app_name")
    )
    culprit_str = ""
    if culprits:
        top3 = ", ".join(app for app, _ in culprits.most_common(3))
        culprit_str = f" Applications pointées par Windows : {top3}."
    out.append(_finding(
        "slow_boot", 68,
        "Démarrage de Windows anormalement lent",
        f"{len(slow)} démarrage(s) de plus de {SLOW_BOOT_MS // 1000} s sur 30 jours "
        f"(le pire : {round(worst / 1000)} s).{culprit_str}",
        "Alléger le démarrage (programmes ci-dessous) ; si un disque mécanique est "
        "en cause, le passage SSD règle aussi ce point.",
    ))


def _rule_overheat(data, out):
    """CPU en surchauffe → bridage (throttling) : la machine est lente PAR le chaud."""
    sensors = data.get("sensors") or {}
    if sensors.get("_status") not in ("ok", None):
        return
    temp = _num(sensors.get("cpu_temp"))
    if temp is None or temp < 90:
        return
    out.append(_finding(
        "cpu_overheat", 65,
        "Processeur en surchauffe — bridage probable",
        f"CPU à {temp}°C mesuré hors charge de test. À ce niveau, le processeur "
        "réduit sa fréquence pour se protéger : la machine est lente parce qu'elle "
        "chauffe.",
        "Dépoussiérage + pâte thermique, puis objectiver le gain avec le bench "
        "thermique avant/après de Ghisdiag.",
    ))


def _rule_av_multiple(data, out):
    """Deux antivirus temps réel qui se scannent mutuellement = machine à genoux."""
    if _v(data, "security", "_status") != "ok":
        return
    active = [a for a in _dicts(_v(data, "security", "antivirus"))
              if a.get("realtime_enabled")]
    if len(active) <= 1:
        return
    names = ", ".join(str(a.get("name") or "?") for a in active)
    out.append(_finding(
        "av_multiple", 52,
        "Plusieurs antivirus actifs en même temps",
        f"{len(active)} protections temps réel simultanées : {names}. Chaque fichier "
        "ouvert est scanné plusieurs fois — impact direct sur toute la machine.",
        "N'en garder qu'un (désinstaller les autres, pas seulement les désactiver).",
    ))


def _rule_cpu_busy(data, out):
    """CPU saturé à l'instant T : constat instantané, avec le processus en tête."""
    if _v(data, "performance", "_status") != "ok":
        return
    load = _num(_v(data, "performance", "cpu", "load_percent"))
    if load is None or load < 80:
        return
    top = _dicts(_v(data, "performance", "cpu", "top_processes"))
    top_str = ""
    if top and top[0].get("name"):
        top_str = f" Processus en tête : {top[0]['name']}."
    out.append(_finding(
        "cpu_busy", 50,
        "Processeur saturé au moment du diagnostic",
        f"Charge CPU à {load}% pendant la collecte.{top_str} Constat instantané : "
        "à confirmer si la lenteur est permanente.",
        "Identifier le processus (mise à jour en cours ? indexation ? malware ?) "
        "via le Gestionnaire des tâches sur la durée.",
    ))


def _rule_startup_bloat(data, out):
    """Trop de programmes lancés au démarrage : session longue à devenir utilisable."""
    if _v(data, "startup", "_status") != "ok":
        return
    progs = _lst(_v(data, "startup", "startup_programs"))
    if len(progs) < STARTUP_BLOAT_MIN:
        return
    out.append(_finding(
        "startup_bloat", 45,
        "Démarrage encombré",
        f"{len(progs)} programmes se lancent avec Windows. Chacun retarde le moment "
        "où la session devient utilisable et occupe RAM/CPU en permanence.",
        "Désactiver les programmes non indispensables (Gestionnaire des tâches → "
        "Applications de démarrage).",
    ))


def _rule_drivers_err(data, out):
    """Pilotes en erreur : périphériques instables, parfois cause de lenteurs/gels."""
    if _v(data, "software", "_status") != "ok":
        return
    errs = _num(_v(data, "software", "drivers", "errors_count"))
    if not errs:
        return
    out.append(_finding(
        "drivers_error", 35,
        "Pilotes en erreur",
        f"{errs} pilote(s) en erreur dans le Gestionnaire de périphériques — "
        "source possible d'instabilités et de lenteurs ponctuelles.",
        "Mettre à jour ou réinstaller les pilotes concernés (détail section "
        "Logiciels & Drivers).",
    ))


_RULES = (
    _rule_hdd,
    _rule_ram,
    _rule_disk_full,
    _rule_disk_failing,
    _rule_slow_boot,
    _rule_overheat,
    _rule_av_multiple,
    _rule_cpu_busy,
    _rule_startup_bloat,
    _rule_drivers_err,
)


def compute_findings(data: dict) -> list[dict]:
    """Applique toutes les règles et retourne les freins triés par impact décroissant.
    `data` = report["data"] (sorties des collecteurs). Ne lève jamais : une règle qui
    plante est ignorée (le rapport doit toujours sortir)."""
    findings: list[dict] = []
    for rule in _RULES:
        try:
            rule(data if isinstance(data, dict) else {}, findings)
        except Exception:
            continue
    findings.sort(key=lambda f: f["score"], reverse=True)
    return findings
