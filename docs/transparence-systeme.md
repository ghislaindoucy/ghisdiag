# Transparence — opérations système effectuées par Ghisdiag

Ce document recense **toutes** les opérations privilégiées de Ghisdiag, pourquoi
elles existent, et à quel moment elles sont déclenchées.

Il a deux publics :

- **les utilisateurs**, qui accordent des droits administrateur à l'outil et ont le
  droit de savoir ce qu'il en fait ;
- **les analystes antivirus**, à qui ce fichier est joint lors des signalements de
  faux positifs — il explique pourquoi un outil de diagnostic légitime présente des
  comportements qui ressemblent, pris isolément, à ceux d'un logiciel malveillant.

**Aucune de ces opérations n'est automatique.** Ghisdiag n'exécute rien au démarrage
en dehors de la collecte de diagnostic en lecture seule. Toute action modifiant le
système est déclenchée par un clic explicite de l'utilisateur.

---

## 1. Architecture

Ghisdiag est une application Python/Tkinter compilée avec PyInstaller. Elle délègue
la collecte et les actions système à des scripts PowerShell embarqués, situés dans
`collectors/`, chacun renvoyant du JSON sur stdout.

Les scripts sont lancés par `run_collector()` et `run_ps_action()`
([orchestrator.py](../orchestrator.py)) avec :

- `powershell.exe` résolu par **chemin absolu** sous `%SystemRoot%\System32`
  (protection contre le détournement de PATH) ;
- `-NoProfile -NonInteractive` ;
- `shell=False` — pas d'interprétation par cmd.exe ;
- `CREATE_NO_WINDOW` — évite le clignotement d'une console noire à chaque appel ;
- une validation du chemin de script (`_validate_script_path`) qui refuse tout
  fichier hors du répertoire d'installation, non `.ps1`, ou atteint par lien
  symbolique.

L'application demande l'élévation administrateur au lancement
([Ghisdiag.manifest](../Ghisdiag.manifest)) : WMI, SMART, les capteurs matériels et
les actions de réparation l'exigent.

**Ghisdiag n'établit aucune connexion réseau sortante**, à une exception près :
l'analyse IA optionnelle, qui envoie le rapport de diagnostic à l'API Mistral —
uniquement si l'utilisateur a saisi sa propre clé API et cliqué sur « Analyser ».

---

## 2. Opérations sensibles, par module

### Profils WiFi — [`collectors/wifi_manager.ps1`](../collectors/wifi_manager.ps1)

C'est le module qui déclenche le plus de détections, car la lecture de clés WiFi est
le cœur d'une famille entière de logiciels voleurs d'identifiants.

| Action | Commande | Déclencheur |
|---|---|---|
| Lister les profils | `netsh wlan show profiles` | Ouverture de l'onglet |
| Afficher un mot de passe | `netsh wlan show profile name="X" key=clear` | Clic sur **un** profil, un à la fois |
| Scanner les réseaux | `netsh wlan show networks mode=bssid` | Clic « Scanner » |
| Se connecter | `netsh wlan add profile` + `netsh wlan connect` | Clic « Connecter » |
| Supprimer un profil | `netsh wlan delete profile` | Clic « Supprimer » |
| Sauvegarder | `netsh wlan export profile` | Clic « Sauvegarder » |
| Restaurer | `netsh wlan add profile filename=...` | Clic « Restaurer » |

Points de conception délibérés :

- **La sauvegarde n'exporte pas les clés en clair par défaut.** Par défaut, les
  profils sont exportés avec la clé chiffrée par DPAPI. L'export en clair
  (`key=clear`) reste disponible — il est indispensable pour restaurer après une
  réinstallation de Windows ou sur une autre machine — mais il exige une
  confirmation explicite dans une boîte de dialogue qui en énonce la conséquence.
  L'objectif est que l'extraction de mots de passe soit toujours un acte délibéré et
  consenti, jamais un effet de bord d'un clic sur « Sauvegarder ».
- **Il n'y a aucune collecte en masse silencieuse.** L'affichage d'un mot de passe se
  fait profil par profil, sur clic.
- **Aucune donnée ne quitte la machine.** La sauvegarde est écrite à l'emplacement
  choisi par l'utilisateur dans une boîte de dialogue « Enregistrer sous ».
- Les noms de profils sont validés contre l'injection d'arguments `netsh`
  (`Test-ProfileName`), et les fichiers temporaires d'export sont supprimés
  immédiatement après compression.

### Journaux d'événements — [`collectors/clear_logs.ps1`](../collectors/clear_logs.ps1)

Utilise `wevtutil cl` pour vider les journaux Windows. L'effacement de journaux est
un indicateur anti-forensique classique, d'où sa contribution au score heuristique.

Usage légitime : après réparation d'un poste, repartir de journaux propres pour que
le diagnostic suivant ne soit pas noyé sous des erreurs déjà corrigées. Déclenché
uniquement par un clic sur « Vider les journaux », avec confirmation.

### BitLocker — [`collectors/bitlocker_manager.ps1`](../collectors/bitlocker_manager.ps1)

`list` (état des volumes via `Get-BitLockerVolume`) et `export` (sauvegarde des clés
de récupération). Lecture de clés de récupération = opération sensible par nature,
mais c'est précisément l'opération qu'un technicien doit faire avant d'intervenir sur
un poste chiffré. Export à l'emplacement choisi par l'utilisateur, sur clic.

### Comptes locaux — [`collectors/user_manager.ps1`](../collectors/user_manager.ps1)

`list-users`, `create-user`, `rename-user`, `set-password-policy`. Création et
modification de comptes locaux — opérations d'administration standard, toutes
déclenchées par formulaire explicite.

### Réparation système — [`collectors/repair.ps1`](../collectors/repair.ps1)

`sfc /scannow` et `DISM /RestoreHealth`. Outils Microsoft, exécutés tels quels.

### Installation de logiciels — [`collectors/winget_manager.ps1`](../collectors/winget_manager.ps1), [`setup_apps.ps1`](../collectors/setup_apps.ps1)

Pilotent `winget` pour lister et installer des mises à jour. Le téléchargement et
l'exécution de binaires tiers passent intégralement par le gestionnaire de paquets
Microsoft — Ghisdiag ne télécharge ni n'exécute rien par lui-même.

### Capteurs matériels — [`collectors/pawnio.py`](../collectors/pawnio.py), `tools/`

La lecture des températures et tensions passe par `LibreHardwareMonitorLib.dll`
(licence MPL 2.0) et, pour certains capteurs, par le pilote **PawnIO**. Un pilote en
mode noyau accédant aux registres MSR est intrinsèquement signalé par les AV.
PawnIO est un composant tiers signé, installé séparément et sur demande explicite —
son installateur (`tools/PawnIO_setup.exe`) n'est jamais lancé automatiquement.

Binaires tiers embarqués dans `tools/` : `smartctl.exe` (smartmontools, GPL v2),
`LibreHardwareMonitorLib.dll`, `HidSharp.dll`, `DiskInfoToolkit.dll` et leurs
dépendances .NET. Licences détaillées dans
[THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md).

### Autres collecteurs

`system_info`, `performance`, `startup`, `events`, `network`, `network_cards`,
`security`, `software`, `smart`, `sensors`, `disk_temp` — **lecture seule**
(WMI/CIM, registre en lecture, `netsh` en consultation). Ils ne modifient rien.

Actions ponctuelles restantes : `spooler_fix.ps1` (redémarrage du spouleur
d'impression), `desktop_icons.ps1` (icônes du bureau), `recovery_drive.ps1`
(inventaire des clés USB, lancement de l'outil Windows natif de création de support
de récupération).

---

## 3. Pourquoi le binaire est signalé

La combinaison suivante suffit à faire franchir le seuil de détection à la plupart
des moteurs heuristiques, alors qu'aucun élément n'est malveillant :

| Caractéristique | Interprétation heuristique |
|---|---|
| Binaire non signé | Éditeur inconnu, aucune réputation |
| PyInstaller `--onefile` | Auto-extraction dans `%TEMP%` puis exécution — schéma de *dropper* |
| `requestedExecutionLevel: requireAdministrator` | Élévation de privilèges |
| PowerShell lancé avec fenêtre masquée et `-ExecutionPolicy Bypass` | Exécution de script dissimulée |
| `netsh wlan ... key=clear` | Lecture d'identifiants réseau |
| `wevtutil cl` | Effacement de traces |
| Lecture de MSR via pilote noyau | Accès matériel bas niveau |

Prise séparément, chaque ligne a une justification métier documentée ci-dessus.
Prises ensemble, elles reproduisent la chaîne comportementale d'un maliciel de type
*infostealer*. C'est un faux positif structurel, pas une erreur ponctuelle de
signature.

`-ExecutionPolicy Bypass` reste nécessaire tant que les scripts `.ps1` ne sont pas
signés numériquement : sans certificat, aucune politique d'exécution plus stricte ne
permettrait à l'outil de fonctionner sur un poste client.

---

## 4. Vérifier l'intégrité d'un binaire publié

Ghisdiag est distribué sous forme d'archive `Ghisdiag.zip`, à décompresser dans un
dossier contenant `Ghisdiag.exe` et son sous-dossier `_internal\`. Chaque version
publiée sur [GitHub Releases](https://github.com/ghislaindoucy/ghisdiag/releases)
indique l'empreinte SHA-256 de l'archive :

```powershell
Get-FileHash Ghisdiag.zip -Algorithm SHA256
```

Les binaires compilés par l'intégration continue disposent en plus d'une
**attestation de provenance signée**, qui prouve que l'archive et l'exécutable
qu'elle contient ont été produits par GitHub Actions à partir du code source
public, au commit indiqué :

```bash
gh attestation verify Ghisdiag.zip --repo ghislaindoucy/ghisdiag
gh attestation verify Ghisdiag.exe --repo ghislaindoucy/ghisdiag
```

---

## 5. Contact

Ghislain DOUCY — <gdoucy@gmail.com>
Code source : <https://github.com/ghislaindoucy/ghisdiag>

Pour tout signalement de sécurité ou demande de précision sur une opération décrite
ici, ouvrez une issue ou écrivez à l'adresse ci-dessus.
