r"""
GhisdiagDisk - point d'entree console.

Pas d'interface graphique dans cette premiere livraison : l'ecran du PE fait
800 x 600 et la console y est lisible ; l'UI tkinter viendra quand le moteur
aura ete valide en atelier. Tout ce que fait ce module, une UI le refera en
appelant les memes fonctions (inventaire, moteur, verdict).

    GhisdiagDisk.exe                     inventaire puis choix interactif
    GhisdiagDisk.exe --lister            inventaire seul
    GhisdiagDisk.exe --disque 1 --mode express --oui
    GhisdiagDisk.exe --reprendre rapports_disque\ghisdiagdisk_XXX.json
    GhisdiagDisk.exe --disque 0 --reprendre        (la plus recente du disque)

Le balayage tourne dans un thread de travail : Ctrl+C dans la console demande
l'arret proprement, la session est ecrite jusqu'a la derniere zone finie.

ATTENTION, piege CPython (atelier du 05/09) : apres un Ctrl+C, le thread de
travail ne peut plus etre attendu ni avec `Thread.join()` ni avec
`Thread.is_alive()`. Quand un KeyboardInterrupt interrompt `join()`,
`Thread._wait_for_tstate_lock` relache le verrou d'etat et appelle `_stop()`
avant de relever l'exception : l'objet Thread se declare TERMINE alors que le
balayage tourne toujours (verifie sur Python 3.12.10). Le fil principal
sortait donc de son attente et affichait << Aucune session produite >> pendant
que la zone en cours finissait de s'ecrire. On attend desormais un
`threading.Event` pose par le worker lui-meme (voir `patienter`).
"""

import argparse
import threading
import time
from pathlib import Path

from . import __version__, OUTIL
from . import inventory, niveaux, rawdisk, scan


def _ligne(txt: str = ""):
    print(txt, flush=True)


def afficher_inventaire(inv: dict):
    ctx = inv["contexte"]
    _ligne(f"{OUTIL} {__version__} - test de sante disque, niveau T1 (lecture seule)")
    _ligne(f"Environnement : {ctx['environnement'].upper()}"
           f"{' (eleve)' if ctx['admin'] else ' (NON eleve)'}"
           f"  |  hote : {ctx['hostname']}{' (inutilisable)' if ctx['hostname_inutile'] else ''}")
    if not ctx["winpe"]:
        _ligne("  ! Hors WinPE : les latences seront mesurees mais NON CONCLUANTES "
               "(I/O de fond de l'OS).")
    if inv.get("avertissement_elevation"):
        _ligne("  ! Aucun disque enumere : sous Windows l'acces brut exige "
               "l'elevation (clic droit > administrateur).")
    excl = inv.get("exclusions") or {}
    if excl.get("indices"):
        _ligne(f"  Exclus d'office : PhysicalDrive{excl['indices']} "
               f"(porteur {excl.get('porteur_exe')}, boot PE {excl.get('boot_pe')})")
    _ligne()
    _ligne(f"  {'#':>2} {'Taille':>9} {'Bus':>5}  {'Type':<30} {'Modele':<28} Cle (confiance)")
    for d in inv["disques"]:
        etat = "" if d["testable"] else "   [EXCLU]"
        _ligne(f"  {d['index']:>2} {str(d['taille_go']) + ' Go':>9} {str(d['bus']):>5}  "
               f"{d['type_support']:<30} {(d['modele'] or '?')[:28]:<28} "
               f"{d['cle_identite']} ({d['confiance_cle']}){etat}")
        for r in d["raisons_exclusion"]:
            _ligne(f"       - exclu : {r}")
        for a in d["avertissements"]:
            _ligne(f"       ! {a}")
    _ligne()


def afficher_fiche(d: dict):
    _ligne(f"Disque #{d['index']} : {d['modele'] or '?'} - {d['taille_go']} Go, "
           f"{d['type_support']}, bus {d['bus']}")
    geo = d.get("geometrie") or {}
    _ligne(f"  secteurs : {geo.get('secteur_logique')} logique / "
           f"{geo.get('secteur_physique')} physique")
    parts = (d.get("partitions") or {})
    if parts:
        _ligne(f"  partitions ({parts.get('schema')}) :")
        for p in parts.get("partitions") or []:
            _ligne(f"    - {p.get('libelle'):<18} {p.get('taille_go'):>8} Go  {p.get('nom') or ''}")
    s = d.get("smart") or {}
    if s:
        attrs = s.get("attributs_ata") or {}
        _ligne(f"  SMART : etat {'OK' if s.get('smart_actif') else s.get('smart_actif')}, "
               f"{s.get('heures')} h, {s.get('temperature')} C"
               + (f", usure NVMe {s.get('usure_nvme_pct')} %" if s.get("usure_nvme_pct") is not None else "")
               + (f", realloues {attrs.get('secteurs_realloues')}, en attente "
                  f"{attrs.get('secteurs_en_attente')}" if attrs else ""))
        if s.get("muet_controleur_raid"):
            _ligne("  SMART muet : controleur RAID/RST - le test de surface est la seule source.")
    else:
        _ligne("  SMART : indisponible pour ce disque")
        if d.get("smart_absence"):
            _ligne(f"    ({d['smart_absence']})")
    if d.get("usure"):
        _ligne(f"  usure projetee : ~{d['usure']['annees_restantes_estimees']} an(s) restant(s) "
               f"({d['usure']['hypothese']})")


def _smart_degrade(d: dict) -> bool:
    s = d.get("smart") or {}
    attrs = s.get("attributs_ata") or {}
    return (s.get("smart_actif") is False
            or any(isinstance(attrs.get(k), (int, float)) and attrs.get(k) > 0
                   for k in ("secteurs_en_attente", "secteurs_realloues",
                             "secteurs_non_corrigeables_hors_ligne",
                             "erreurs_non_corrigeables_rapportees")))


def _demander(question: str) -> str:
    try:
        return input(question).strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def patienter(fin: threading.Event, annulation: threading.Event,
              annoncer=None, pas: float = 0.5) -> bool:
    """Attend que le thread de balayage pose `fin`. Rend True si un arret a
    ete demande.

    Ctrl+C, autant de fois qu'on veut, pose `annulation` et NE FAIT PAS sortir
    de l'attente : le moteur doit finir sa zone et ecrire la session. Tout le
    corps de la boucle est dans le `try` pour qu'une interruption arrivee
    pendant le message ne s'echappe pas non plus.

    On n'utilise ni `join()` ni `is_alive()` : voir l'avertissement en tete de
    module (apres un Ctrl+C, l'objet Thread ment sur son etat).
    """
    annonce = False
    while not fin.is_set():
        try:
            if annulation.is_set() and not annonce:
                annonce = True
                if annoncer is not None:
                    annoncer()
            fin.wait(pas)
        except KeyboardInterrupt:
            annulation.set()
    return annulation.is_set()


def executer_balayage(fiche: dict, cfg: scan.ScanConfig, ctx: dict,
                      dossier: Path, session=None, pas: float = 0.5) -> dict:
    """Lance le moteur sur le disque reel, avec progression console et
    arret propre sur Ctrl+C. Rend la session terminee."""
    annulation = threading.Event()
    fin = threading.Event()
    etat = {"session": None, "erreur": None, "derniere": None}
    chemin = {"p": None}

    def _checkpoint(s):
        if chemin["p"] is None:
            chemin["p"] = scan.chemin_session(dossier, s)
        etat["derniere"] = s          # filet : de quoi conclure meme si run() ne rend rien
        scan.sauver_session(s, chemin["p"])

    def _progression(fraction, texte):
        print(f"\r  {fraction * 100:5.1f} %  {texte:<40}", end="", flush=True)

    def _segment(s, res):
        alerte = ""
        if res["nb_blocs_illisibles"]:
            alerte = f"  ILLISIBLE : {res['nb_secteurs_illisibles']} secteur(s)"
        elif res["nb_blocs_anormaux"]:
            alerte = f"  {res['nb_blocs_anormaux']} bloc(s) lent(s), max {res['bloc_max_ms']} ms"
        elif res.get("nb_blocs_isoles"):
            alerte = f"  ({res['nb_blocs_isoles']} bloc(s) lent(s) isole(s), max {res['bloc_max_ms']} ms)"
        print(f"\r  zone {res['index'] + 1:>3} @ {res['offset_go']:>8.1f} Go : "
              f"{str(res['debit_mo_s']):>7} Mo/s  med {res['bloc_median_ms']} ms  "
              f"max {res['bloc_max_ms']} ms{alerte}", flush=True)

    def _travail():
        try:
            with rawdisk.LecteurDisque(fiche["index"], cfg.normalized().bloc_octets) as lecteur:
                moteur = scan.ScanEngine(lecteur, fiche, cfg, ctx, session=session,
                                         on_segment=_segment, on_progression=_progression,
                                         checkpoint=_checkpoint, annulation=annulation)
                etat["session"] = moteur.run()
        except BaseException as exc:      # noqa: BLE001 - remonte au thread principal
            etat["erreur"] = exc
        finally:
            fin.set()                     # pose QUOI QU'IL ARRIVE : c'est la seule
                                          # attente fiable apres un Ctrl+C

    th = threading.Thread(target=_travail, name="GhisdiagDiskScan", daemon=True)
    th.start()
    patienter(fin, annulation, annoncer=lambda: _ligne(
        "\n  Arret demande - fin de la zone en cours, puis ecriture de la session..."))
    if etat["erreur"] is not None:
        raise etat["erreur"]
    s = etat["session"]
    if s is None and etat["derniere"] is not None:
        # Le moteur n'a pas rendu la main mais des zones sont ecrites : on
        # conclut sur ce qui a ete mesure plutot que de ne rien dire.
        s = etat["derniere"]
        s.setdefault("statut", "interrompu")
        s["synthese"] = scan.synthese(s)
        s["verdict"] = scan.calculer_verdict(s)
    if s is not None:
        s["_fichier"] = str(chemin["p"]) if chemin["p"] else None
    return s


def sessions_reprenables(dossier) -> list:
    """Sessions du dossier qu'on peut reprendre, la plus recente d'abord.

    Un arret de securite (trop de blocs illisibles) n'est PAS reprenable :
    on imagerait d'abord, on testerait ensuite.
    """
    out = []
    try:
        fichiers = list(Path(dossier).glob("ghisdiagdisk_*.json"))
    except OSError:
        return out
    for f in fichiers:
        s = scan.charger_session(f)
        if not s or s.get("statut") not in ("interrompu", "en_cours"):
            continue
        d = s.get("disque") or {}
        out.append({"fichier": f, "session": s, "cle": d.get("cle_identite"),
                    "modele": d.get("modele"), "mode": s.get("mode"),
                    "zones": len(s.get("segments") or []),
                    "prevues": (s.get("plan") or {}).get("nb_segments"),
                    "demarre_a": s.get("demarre_a") or ""})
    out.sort(key=lambda x: x["demarre_a"], reverse=True)
    return out


def resoudre_reprise(valeur: str, dossier, cle_disque=None):
    """-> (session, chemin) ou (None, None) apres avoir explique et propose.

    `valeur` est un chemin de fichier, un dossier, ou "auto" (= la session
    reprenable la plus recente, du disque choisi s'il est connu). Taper un nom
    de fichier a la main en WinPE est penible : --reprendre sans argument doit
    marcher.
    """
    candidats = None
    if valeur and valeur != "auto":
        p = Path(valeur)
        if p.is_file():
            s = scan.charger_session(p)
            if s:
                return s, p
            _ligne(f"[ERREUR] fichier illisible ou ce n'est pas une session : {valeur}")
        elif p.is_dir():
            candidats = sessions_reprenables(p)
        else:
            _ligne(f"[ERREUR] fichier introuvable : {valeur}")
    if candidats is None:
        candidats = sessions_reprenables(dossier)
    if cle_disque:
        retenus = [c for c in candidats if c["cle"] == cle_disque]
    else:
        retenus = candidats
    if valeur == "auto" and retenus:
        c = retenus[0]
        return c["session"], c["fichier"]
    if not candidats:
        _ligne(f"Aucune session reprenable dans {dossier}")
        _ligne("  (une session est reprenable si elle a ete interrompue par Ctrl+C)")
        return None, None
    _ligne(f"\nSessions reprenables dans {dossier} :")
    for c in candidats:
        _ligne(f"  {c['fichier'].name}")
        _ligne(f"      {c['modele'] or '?'} ({c['cle']}) - mode {c['mode']}, "
               f"{c['zones']}/{c['prevues']} zone(s) faite(s), du {c['demarre_a']}")
    _ligne("\nA relancer avec le nom exact, par exemple :")
    _ligne(f"  GhisdiagDisk.exe --reprendre rapports_disque\\{candidats[0]['fichier'].name}")
    _ligne("  ou simplement :  GhisdiagDisk.exe --disque N --reprendre")
    return None, None


def afficher_verdict(s: dict):
    v = s.get("verdict") or {}
    syn = s.get("synthese") or {}
    _ligne()
    _ligne(f"VERDICT : {scan.LIBELLES_ETAT.get(v.get('etat'), '?')}   "
           f"({v.get('portee')}, {syn.get('couverture_disque_pct')} % de la surface, "
           f"statut {s.get('statut')}, {s.get('duree_s')} s)")
    for r in v.get("raisons") or []:
        _ligne(f"  - {r}")
    for n in v.get("notes") or []:
        _ligne(f"  . {n}")
    _ligne(f"  debit median {syn.get('debit_median_mo_s')} Mo/s "
           f"(min {syn.get('debit_min_mo_s')}, max {syn.get('debit_max_mo_s')}), "
           f"bloc max {syn.get('bloc_max_ms')} ms")
    la = s.get("lecture_aleatoire") or {}
    if la:
        _ligne(f"  lecture aleatoire {la.get('taille_lecture')} o : p50 {la.get('p50_ms')} ms, "
               f"p99 {la.get('p99_ms')} ms, max {la.get('max_ms')} ms, erreurs {la.get('erreurs')}")
    _ligne(f"  {s.get('mention_niveau')}")
    if s.get("_fichier"):
        _ligne(f"  session : {s['_fichier']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog=OUTIL, description="Test de sante disque T1 (lecture seule).")
    ap.add_argument("--lister", action="store_true", help="inventaire seul")
    ap.add_argument("--disque", type=int, help="index PhysicalDriveN a tester")
    ap.add_argument("--mode", choices=scan.MODES, default="express")
    ap.add_argument("--niveau", default=niveaux.NIVEAU_DEFAUT, help="T1 (seul implemente)")
    ap.add_argument("--reprendre", nargs="?", const="auto", default=None,
                    help="fichier de session a reprendre ; sans valeur, la plus "
                         "recente session interrompue (du disque choisi)")
    ap.add_argument("--sortie", help="dossier des sessions (defaut : rapports_disque\\ a cote de l'exe)")
    ap.add_argument("--sans-smart", action="store_true", help="ne pas interroger smartctl")
    ap.add_argument("--oui", action="store_true", help="ne pas demander confirmation")
    ap.add_argument("--segments", type=int, help="nombre de zones (express/standard)")
    args = ap.parse_args(argv)

    try:
        niveaux.verifier_niveau(args.niveau)
    except niveaux.NiveauRefuse as exc:
        _ligne(f"[REFUS] {exc}")
        return 2

    inv = inventory.inventaire_machine(avec_smart=not args.sans_smart)
    afficher_inventaire(inv)
    if args.lister:
        return 0
    ctx = inv["contexte"]
    testables = {d["index"]: d for d in inv["disques"] if d["testable"]}
    if not testables:
        _ligne("Aucun disque testable.")
        return 1

    dossier = scan.dossier_sessions(Path(args.sortie) if args.sortie else None)

    session = None
    if args.reprendre:
        vise = testables.get(args.disque) if args.disque is not None else None
        session, fichier = resoudre_reprise(args.reprendre, dossier,
                                            vise["cle_identite"] if vise else None)
        if not session:
            return 1
        cle = (session.get("disque") or {}).get("cle_identite")
        cible = next((d for d in testables.values() if d["cle_identite"] == cle), None)
        if cible is None:
            _ligne(f"[ERREUR] le disque de la session ({cle}) n'est pas present ou pas testable.")
            return 1
        args.disque = cible["index"]
        args.mode = session.get("mode", args.mode)
        _ligne(f"Reprise de {Path(fichier).name} sur le disque #{cible['index']} "
               f"({len(session.get('segments') or [])} zone(s) deja faite(s) sur "
               f"{(session.get('plan') or {}).get('nb_segments')}).")

    if args.disque is None:
        rep = _demander(f"Disque a tester {sorted(testables)} (vide = quitter) : ")
        if not rep.isdigit() or int(rep) not in testables:
            _ligne("Abandon.")
            return 0
        args.disque = int(rep)
    if args.disque not in testables:
        _ligne(f"[REFUS] PhysicalDrive{args.disque} n'est pas testable.")
        return 2
    fiche = testables[args.disque]
    _ligne()
    afficher_fiche(fiche)

    if _smart_degrade(fiche) and args.mode != "express":
        _ligne()
        _ligne("  !!! SMART est deja degrade sur ce disque. Balayer longuement un disque")
        _ligne("      mourant peut l'achever : IMAGER D'ABORD, tester ensuite. Le mode")
        _ligne("      express suffit a documenter l'etat sans le pousser.")
    if not args.oui:
        rep = _demander(f"\nLancer le balayage {args.mode} T1 (lecture seule) du disque "
                        f"#{args.disque} ? [o/N] ")
        if rep.lower() not in ("o", "oui", "y", "yes"):
            _ligne("Abandon.")
            return 0

    cfg = scan.ScanConfig(mode=args.mode, niveau=args.niveau, nb_segments=args.segments)
    if session is not None:
        try:
            session = scan.reprendre_session(session, fiche)
        except ValueError as exc:
            _ligne(f"[REFUS] {exc}")
            return 2
        cfg = scan.ScanConfig(**{k: v for k, v in session["config"].items()})
    _ligne(f"\nSessions ecrites dans : {dossier}")
    _ligne(f"Balayage {cfg.mode} - {len(scan.planifier(fiche['geometrie']['taille_octets'], fiche['geometrie']['secteur_logique'], cfg))} zone(s). Ctrl+C pour arreter proprement.\n")
    t0 = time.monotonic()
    s = executer_balayage(fiche, cfg, ctx, dossier, session=session)
    if s is None:
        _ligne("Aucune zone n'a pu etre mesuree - aucune session ecrite.")
        _ligne(f"  (les sessions vont dans {dossier})")
        return 1
    afficher_verdict(s)
    _ligne(f"  ({round(time.monotonic() - t0)} s ecoulees)")
    return 0 if (s.get("verdict") or {}).get("etat") in ("sain", "non_concluant") else 3
