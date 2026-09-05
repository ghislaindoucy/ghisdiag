r"""
GhisdiagDisk - les trois niveaux de test, separes STRUCTURELLEMENT.

    T1  lecture seule            n'ecrit rien, jamais           (livre)
    T2  ecriture sur espace libre fichier temporaire via NTFS    (plus tard)
    T3  ecriture brute pleine surface  DESTRUCTION TOTALE        (plus tard)

Une case << mode destructif >> est la mecanique meme de l'accident : elle reste
cochee de la machine precedente, ou on la coche sur le mauvais disque. Ici :

  - le niveau est un ATTRIBUT DE LA SESSION, ecrit dans le rapport ;
  - T3 n'est propose que si le fichier-marqueur ECRITURE_DESTRUCTIVE_AUTORISEE.txt
    est present a cote de l'exe. La cle d'atelier courante ne le contient pas :
    elle est physiquement incapable de detruire quoi que ce soit ;
  - aucune persistance du choix : T1 au lancement, toujours.

Poser cette architecture DES LA V1, meme si seul T1 est livre : greffer un mode
destructif apres coup sur une base qui n'a jamais ecrit, c'est la qu'on se
blesse.
"""

from pathlib import Path
from typing import Optional

NIVEAUX = ("T1", "T2", "T3")
NIVEAU_DEFAUT = "T1"
MARQUEUR_T3 = "ECRITURE_DESTRUCTIVE_AUTORISEE.txt"

DESCRIPTIONS = {
    "T1": "Lecture seule - aucune ecriture sur le disque, contenu preserve.",
    "T2": "Ecriture sur espace libre (fichier temporaire) - non destructif.",
    "T3": "Ecriture brute pleine surface - DESTRUCTION TOTALE du contenu.",
}

# Phrase reprise en en-tete du rapport client, en clair. Un rapport horodate
# qui dit noir sur blanc << aucune ecriture >> clot une discussion.
MENTION_RAPPORT = {
    "T1": "Test non destructif - aucune ecriture sur les donnees existantes, "
          "contenu du disque preserve.",
    "T2": "Test non destructif - un fichier temporaire a ete cree puis supprime "
          "sur l'espace libre, contenu du disque preserve.",
    "T3": "TEST DESTRUCTIF - l'integralite du contenu du disque a ete effacee.",
}

IMPLEMENTES = ("T1",)


def marqueur_t3_present(dossier: Optional[Path] = None) -> bool:
    if dossier is None:
        from . import rawdisk
        dossier = rawdisk.dossier_exe()
    return (Path(dossier) / MARQUEUR_T3).is_file()


def niveaux_autorises(dossier: Optional[Path] = None) -> tuple:
    """Niveaux que CETTE cle a le droit de proposer (independamment de ce qui
    est implemente) : T3 exige le marqueur, T1 et T2 sont toujours proposables."""
    if marqueur_t3_present(dossier):
        return NIVEAUX
    return ("T1", "T2")


class NiveauRefuse(Exception):
    pass


def verifier_niveau(niveau: str, dossier: Optional[Path] = None) -> str:
    """Valide un niveau avant d'ouvrir la moindre session. Leve NiveauRefuse.

    Un niveau non implemente est refuse EXPLICITEMENT (jamais retrograde en
    silence vers T1 : le technicien croirait avoir fait un test d'ecriture).
    """
    if niveau not in NIVEAUX:
        raise NiveauRefuse(f"niveau inconnu : {niveau!r} (attendu : {', '.join(NIVEAUX)})")
    if niveau not in niveaux_autorises(dossier):
        raise NiveauRefuse(
            f"{niveau} refuse : le fichier-marqueur {MARQUEUR_T3} est absent a cote "
            "de l'executable. Cette cle ne peut pas ecrire sur un disque.")
    if niveau not in IMPLEMENTES:
        raise NiveauRefuse(f"{niveau} n'est pas encore implemente "
                           f"(disponible : {', '.join(IMPLEMENTES)}).")
    return niveau
