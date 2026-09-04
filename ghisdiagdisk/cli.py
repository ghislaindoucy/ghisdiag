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

Le balayage tourne dans un thread de travail : Ctrl+C dans la console demande
l'arret proprement, la session est ecrite jusqu'a la derniere zone finie.
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


def executer_balayage(fiche: dict, cfg: scan.ScanConfig, ctx: dict,
                      dossier: Path, session=None) -> dict:
    """Lance le moteur sur le disque reel, avec progression console et
    arret propre sur Ctrl+C. Rend la session terminee."""
    annulation = threading.Event()
    etat = {"session": None, "erreur": None}
    chemin = {"p": None}

    def _checkpoint(s):
        if chemin["p"] is None:
            chemin["p"] = scan.chemin_session(dossier, s)
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
        except Exception as exc:          # noqa: BLE001 - remonte au thread principal
            etat["erreur"] = exc

    th = threading.Thread(target=_travail, name="GhisdiagDiskScan", daemon=True)
    th.start()
    try:
        while th.is_alive():
            th.join(0.5)
    except KeyboardInterrupt:
        _ligne("\n  Arret demande - fin de la zone en cours, puis ecriture de la session...")
        annulation.set()
        while th.is_alive():
            try:
                th.join(0.5)
            except KeyboardInterrupt:
                pass
    if etat["erreur"] is not None:
        raise etat["erreur"]
    s = etat["session"]
    if s is not None:
        s["_fichier"] = str(chemin["p"]) if chemin["p"] else None
    return s


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
    ap.add_argument("--reprendre", help="fichier de session a reprendre")
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

    session = None
    if args.reprendre:
        session = scan.charger_session(args.reprendre)
        if not session:
            _ligne(f"[ERREUR] session illisible : {args.reprendre}")
            return 1
        cle = (session.get("disque") or {}).get("cle_identite")
        cible = next((d for d in testables.values() if d["cle_identite"] == cle), None)
        if cible is None:
            _ligne(f"[ERREUR] le disque de la session ({cle}) n'est pas present ou pas testable.")
            return 1
        args.disque = cible["index"]
        args.mode = session.get("mode", args.mode)
        _ligne(f"Reprise de la session {args.reprendre} sur le disque #{cible['index']} "
               f"({len(session.get('segments') or [])} zone(s) deja faite(s)).")

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
    dossier = scan.dossier_sessions(Path(args.sortie) if args.sortie else None)
    _ligne(f"\nSessions ecrites dans : {dossier}")
    _ligne(f"Balayage {cfg.mode} - {len(scan.planifier(fiche['geometrie']['taille_octets'], fiche['geometrie']['secteur_logique'], cfg))} zone(s). Ctrl+C pour arreter proprement.\n")
    t0 = time.monotonic()
    s = executer_balayage(fiche, cfg, ctx, dossier, session=session)
    if s is None:
        _ligne("Aucune session produite.")
        return 1
    afficher_verdict(s)
    _ligne(f"  ({round(time.monotonic() - t0)} s ecoulees)")
    return 0 if (s.get("verdict") or {}).get("etat") in ("sain", "non_concluant") else 3
