# Ghisdiag v2.3.0 — fiche machine à l'ouverture + durcissement sécurité

Cette version ajoute une **fiche machine** consultée d'un coup d'œil à l'ouverture
de l'app, deux commodités d'impression, et surtout **quatre correctifs de sécurité**
issus d'un audit interne — dont une injection de commande qui pouvait exécuter du
code en administrateur.

---

## 🖥️ Fiche machine (onglet Setup / MAJ)

Un nouveau sous-onglet **« Machine »**, placé en tête, donc affiché dès le
lancement. Tout ce qu'un technicien veut voir avant d'intervenir, en lecture seule :

- **Identité** : modèle avec son nom commercial (« ThinkStation P330 », pas que la
  référence), numéro de série, portable/fixe, rattachement (domaine, groupe de
  travail, Entra ID), BIOS.
- **Windows** : édition, version et build, **activation** (canal, clé OEM dans le
  BIOS), date d'installation, temps depuis le démarrage, redémarrage en attente.
- **Processeur, mémoire** (détail des barrettes), **carte(s) graphique(s)**.
- **Stockage** par disque (SSD NVMe/SATA, USB, état) avec ses volumes, barres
  d'usage et état **BitLocker**.
- **Comptes** locaux **et Microsoft — avec l'adresse e-mail**, rôle admin/standard,
  état, dernière activité ; profils de domaine ou Entra ID.
- **Sécurité** (antivirus, TPM, Secure Boot, firmware), **batterie** (charge, usure,
  cycles), **réseau** (cartes réelles, IP, MAC), **périphériques en erreur**.
- **« Points d'attention »** en tête, triés par gravité (Windows non activé, disque
  plein ou défaillant, BitLocker actif, pilote manquant, batterie usée…).
- Bouton **« Copier la fiche »** pour un ticket ou une fiche d'intervention.

Règle de fond : une valeur **non lue** ne s'affiche jamais comme une valeur. Un TPM
illisible faute de droits n'est pas un TPM « absent », un BitLocker illisible n'est
pas « désactivé ».

## 🖨️ Dépannage — impression

- **Définir l'imprimante par défaut** en un clic. Le réglage coupe d'abord « Laisser
  Windows gérer mon imprimante par défaut » (sinon Windows reprend la main au premier
  travail), et le succès est **vérifié par relecture**, pas supposé.
- Raccourci vers l'ancien gestionnaire **« Périphériques et imprimantes »**.

## 🔒 Sécurité — 4 correctifs (audit du 13/09/2026)

- **Injection de commande PowerShell.** Les arguments des scripts (SSID, nom
  d'imprimante, chemin, mot de passe) étaient insérés dans une ligne `-Command`
  construite en texte. Deux failles : une valeur commençant par `-`, et l'apostrophe
  typographique `’`, permettaient d'exécuter du code **en administrateur** — par
  exemple via un réseau WiFi malveillant qu'on sélectionne. Les arguments passent
  maintenant en JSON sur l'entrée standard, appliqués par *splatting* : une valeur
  reste une donnée, jamais du code.
- **DLL capteurs chargées depuis un dossier modifiable sans droits.** L'app ne
  charge plus de bibliothèque depuis `%LOCALAPPDATA%` ni depuis une variable
  d'environnement (un malware sans privilèges pouvait y déposer une DLL, chargée
  ensuite en admin). Seuls l'embarqué et le dossier `tools\` à côté de l'exe.
- **Clé API Gemini** sortie de l'URL (elle fuyait dans les journaux et les messages
  d'erreur) : elle part désormais dans un en-tête, et toute clé est masquée des
  messages.
- **Chiffrement des clés API renforcé.** L'ancienne clé de chiffrement se déduisait
  du nom de la machine et de l'utilisateur — présents dans chaque rapport. Remplacé
  par **DPAPI** de Windows, lié à ta session. Migration automatique de tes clés
  existantes ; plus jamais de clé écrite en clair.

---

## Vérifier l'archive téléchargée

- **Nom** : `Ghisdiag.zip`
- **Taille** : `__SIZE__`
- **SHA-256** :

```
__SHA256__
```

Pour contrôler l'empreinte après téléchargement (PowerShell, dans le dossier de
l'archive) :

```powershell
Get-FileHash Ghisdiag.zip -Algorithm SHA256
```

L'archive est aussi couverte par une **attestation de provenance SLSA** générée par
GitHub Actions, vérifiable avec :

```
gh attestation verify Ghisdiag.zip --owner ghislaindoucy
```

---

## Installation

1. Télécharge `Ghisdiag.zip`, décompresse-le où tu veux (disque local ou clé USB).
2. Double-clique sur `Ghisdiag.exe` dans le dossier obtenu ; accepte l'élévation.

**Prérequis** : Windows 10/11, rien d'autre (tout est embarqué). Garde le dossier
entier — `Ghisdiag.exe` a besoin du sous-dossier `_internal\` à côté de lui. La
notice PDF est livrée dans le dossier.

**Note pour qui utilise déjà l'analyse IA** : tes clés API seront ré-enregistrées au
format DPAPI au premier lancement. Aucune action de ta part.
