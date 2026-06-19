# Ghisdiag v1.2.3 — Notes de Release

**Date de sortie :** 2026-06-10  
**Version précédente :** 1.2.2

---

> Petite release ciblée « PC Neuf » : on gagne **VLC**, un bouton **icônes du bureau**,
> et surtout on solidifie **winget** pour de bon (fini le « fichier introuvable » en admin).

---

## 🆕 Onglet PC Neuf — VLC media player

VLC rejoint le catalogue des logiciels installables en silence via winget.

- Identifiant winget : `VideoLAN.VLC`
- Apparaît automatiquement dans la liste cochable, la vérification « installés » et l'installation
- Installation silencieuse, en français, sans interaction — comme les autres

---

## 🖥️ Onglet PC Neuf — Icônes du bureau en 1 clic

Nouveau bouton **« Ajouter les icônes du bureau »**. D'un clic, il affiche sur le bureau :

| Icône | Comportement |
|-------|--------------|
| **Ce PC** | Affichée si absente |
| **Fichiers de l'utilisateur** | Affichée si absente |
| **Corbeille** | Affichée **si elle n'y est pas déjà** |

### Sous le capot

- Modification du registre `HideDesktopIcons\NewStartPanel` (par CLSID)
- Rafraîchissement immédiat du bureau via `SHChangeNotify` — **sans redémarrer l'explorateur**
- S'exécute en `HKCU` : **aucun droit administrateur requis**
- Le journal indique pour chaque icône si elle a été **ajoutée** ou était **déjà présente**

---

## 🔧 Fiabilité winget — la vraie correction

### Le problème

Sur certaines machines, l'installation PC Neuf échouait avec :

> *« Le programme winget.exe n'a pas pu s'exécuter : Le fichier spécifié est introuvable »*

En cause : le chemin « évident » de winget
(`…\AppData\Local\Microsoft\WindowsApps\winget.exe`) est un **alias d'exécution de 0 octet**.
Invoqué par chemin complet — surtout depuis un processus **élevé (admin)** — il échoue.

### La correction

`Get-WingetPath` **teste désormais réellement chaque candidat** (`winget --version`) et garde
le premier qui répond vraiment :

1. Vrai `winget.exe` via le package AppX (`Get-AppxPackage`)
2. Recherche directe dans `Program Files\WindowsApps`
3. Commande nue `winget` (résolution d'alias par l'OS)
4. Stub d'alias — uniquement en dernier recours

Appliqué dans **`setup_apps.ps1`** (PC Neuf) **et** **`winget_manager.ps1`** (onglet Mises à jour).

### Bonus détection

- La vérification « installés » interroge chaque app par son **ID exact**
  (`winget list --id … --exact`) → fini les faux « non installé » dus à la
  **troncature de la colonne Id** en sortie redirigée
- Statut explicite par application : **✓ Installé** / **✗ Non installé**
- Messages de progression et de fin dans le journal (plus de « rien ne se passe »)

---

## ✅ Vérification Pré-Release

- ✅ `main.py` compile (`py -m py_compile`)
- ✅ `setup_apps.ps1`, `winget_manager.ps1`, `desktop_icons.ps1` parsent sans erreur
- ✅ `desktop_icons.ps1 -Action check` renvoie un JSON valide
- ✅ Versions synchronisées (orchestrator, version_info, README, mistral_report)

---

## 🚀 À Savoir Avant le Déploiement

1. **winget requis pour PC Neuf** : si winget est cassé sur la machine, l'app affiche
   maintenant proprement « winget non disponible » et invite à passer par l'onglet Mises à jour.
2. **Icônes du bureau** : effet immédiat, réversible depuis les paramètres Windows si besoin.
3. **Aucune nouvelle dépendance Python.**

---

## 📝 Modifications

```
feat(pcneuf): VLC ajouté au catalogue winget
feat(pcneuf): bouton « Ajouter les icônes du bureau » (Ce PC, Utilisateur, Corbeille)
fix(winget): résolution robuste de winget.exe (fin du « fichier introuvable » en admin)
fix(pcneuf): détection « déjà installé » par ID exact + retour visuel de la vérification
```

---

## ⬇️ Téléchargement

- **Exe** : `Ghisdiag.exe`
- **Sha256** : _(à compléter après build)_
- **Taille** : _(à compléter après build)_
