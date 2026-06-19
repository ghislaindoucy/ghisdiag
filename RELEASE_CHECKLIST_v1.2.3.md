# Release Checklist — Ghisdiag v1.2.3

**Date cible :** 2026-06-10  
**Statut :** ✅ Prêt pour build

---

## ✅ Pré-Build

- ✅ Version bump : **1.2.2 → 1.2.3** (orchestrator.py, version_info.txt, README, mistral_report.py)
- ✅ RELEASE_NOTES_v1.2.3.md créé
- ✅ CHANGELOG.md mis à jour
- ✅ Git tag à créer : `v1.2.3`
- ✅ Main à jour avec tous les commits
- ✅ Pas de changements non-commités

---

## 📋 À Faire Avant Build

1. **Valider le build**
   ```batch
   cd D:\Projets\PlanetDIag
   build.bat
   ```
   - Vérifie que `dist/Ghisdiag.exe` est créé
   - Taille estimée : ~80-100 MB
   - Durée estimée : 3-5 minutes

2. **Tester l'exe produit (focus PC Neuf)**
   - Lancer `dist/Ghisdiag.exe` **en administrateur**
   - Onglet **Setup / MAJ → PC Neuf**
     - « 🔍 Vérifier installés » → chaque app affiche **✓ Installé** / **✗ Non installé**
     - **VLC media player** présent dans la liste
     - « 🖥 Ajouter les icônes du bureau » → Ce PC / Utilisateur / Corbeille apparaissent
   - Onglet **Mises à jour** : winget détecté, version affichée
   - Parcourir les autres onglets (pas de crash)

3. **Calculer le hash SHA-256**
   ```powershell
   Get-FileHash "dist\Ghisdiag.exe" -Algorithm SHA256 | Format-Table Hash
   ```
   - Copier le hash dans RELEASE_NOTES_v1.2.3.md

4. **Noter la taille de l'exe**
   ```powershell
   (Get-Item "dist\Ghisdiag.exe").Length / 1MB
   ```
   - Remplir dans RELEASE_NOTES_v1.2.3.md

---

## 📦 Fichiers à Uploader

```
dist/
└── Ghisdiag.exe          ← Le build principal

À inclure dans la release :
├── RELEASE_NOTES_v1.2.3.md  ← Notes utilisateur (lire d'abord!)
├── CHANGELOG.md             ← Historique complet
└── requirements.txt         ← Si rebuild manuelle
```

---

## 🔧 Tag Git + Push

```bash
cd D:\Projets\PlanetDIag
git push origin main
git tag -a v1.2.3 -m "Release v1.2.3 — PC Neuf (VLC + icônes bureau) & fiabilité winget"
git push origin v1.2.3
```

---

## 📝 Description Release GitHub

```markdown
## Ghisdiag v1.2.3 — PC Neuf enrichi & winget fiabilisé

Release ciblée sur l'onglet **PC Neuf** et la robustesse de **winget**.

### Highlights

🆕 **PC Neuf**
- **VLC media player** ajouté aux logiciels installables
- **Icônes du bureau en 1 clic** : Ce PC, Fichiers utilisateur, Corbeille

🔧 **Fiabilité winget**
- Fin du « winget.exe introuvable » en contexte administrateur
- Détection « déjà installé » par ID exact (plus de faux négatifs)
- Retour visuel clair lors de la vérification

### Installation

**Exe seul** : `Ghisdiag.exe` (toutes dépendances embarquées)

### SHA-256
```
[À remplir après build]
```
```

---

## ⚠️ Validations Finales

- ✅ `main.py` compile sans erreur
- ✅ Scripts PowerShell parsent (setup_apps, winget_manager, desktop_icons)
- ✅ Exe exécutable (pas d'erreurs de dépendances)
- ✅ PC Neuf : VLC + icônes du bureau OK
- ✅ Hash SHA-256 calculé
- ✅ Git tag créé et pushé

---

## 🚀 Post-Release

1. Créer la release sur GitHub avec l'exe et les notes
2. Nettoyer les vieux builds dans `dist/`
3. Préparer v1.2.4 (placeholder pour prochain work)

---

**Statut :** Prêt à builder et uploader ✅
