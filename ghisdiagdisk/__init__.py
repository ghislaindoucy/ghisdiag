r"""
GhisdiagDisk - outil de test de sante disque autonome et bootable (WinPE).

Second executable du depot Ghisdiag, PAS un module de l'application : les
disques a tester sont ceux des machines qui ne demarrent plus. Conception et
mesures de calibration dans ROADMAP.md, section "Chantiers prepares" >
GhisdiagDisk - a lire avant de toucher a quoi que ce soit ici.

Perimetre impose par WinPE (ni .NET ni PowerShell) : Python + ctypes sur
\\.\PhysicalDriveN + smartctl.exe. Rien d'autre.

Modules :
    rawdisk    acces Win32 brut (enumeration, identite IOCTL, partitions,
               lecteur non bufferise aligne)
    smart      lecture SMART via smartctl (type conserve, deduplication)
    inventory  fiche par disque : cle d'identite composite, type de support,
               regles d'exclusion et avertissements
    niveaux    T1 / T2 / T3 - separation structurelle (fichier-marqueur)
    scan       LE moteur de balayage T1 : plan express/standard/complet,
               echauffement, anomalies de latence, secteurs illisibles,
               session checkpointee et reprise, verdict tri-etat
    cli        point d'entree console (WinPE 800x600, sans UI graphique)
"""

__version__ = "0.1.0"
OUTIL = "GhisdiagDisk"
