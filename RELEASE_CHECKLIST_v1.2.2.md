# Release Checklist — PlanetDiag v1.2.2

**Date cible :** 2025-06-03  
**Statut :** ✅ Prêt pour build

---

## ✅ Pré-Build

- ✅ Version bump (version_info.txt) : **1.2.1 → 1.2.2**
- ✅ RELEASE_NOTES_v1.2.2.md créé
- ✅ CHANGELOG.md créé
- ✅ Git tag à créer : `v1.2.2`
- ✅ Main à jour avec tous les commits
- ✅ Pas de changements non-commités

---

## 📋 À Faire Avant Build

1. **Valider le build**
   ```batch
   cd D:\Projets\PlanetDIag
   build.bat
   ```
   - Vérifie que `dist/PlanetDiag.exe` est créé
   - Taille estimée : ~80-100 MB
   - Durée estimée : 3-5 minutes

2. **Tester l'exe produit**
   - Double-cliquer sur `dist/PlanetDiag.exe`
   - Vérifier que l'interface démarre en mode maximisé
   - Vérifier que le panneau Mistral est visible dans l'onglet Analyse
   - Tester le bouton "Tester la clé" (ou affiche erreur dépendances manquantes)
   - Parcourir les onglets (pas de crash)

3. **Calculer le hash SHA-256**
   ```powershell
   Get-FileHash "dist\PlanetDiag.exe" -Algorithm SHA256 | Format-Table Hash
   ```
   - Copier le hash dans RELEASE_NOTES_v1.2.2.md

4. **Noter la taille de l'exe**
   ```powershell
   (Get-Item "dist\PlanetDiag.exe").Length / 1MB
   ```
   - Remplir dans RELEASE_NOTES_v1.2.2.md

---

## 📦 Fichiers à Uploader

```
dist/
└── PlanetDiag.exe          ← Le build principal

À inclure dans la release :
├── RELEASE_NOTES_v1.2.2.md  ← Notes utilisateur (lire d'abord!)
├── CHANGELOG.md             ← Historique complet
├── requirements.txt         ← Si rebuild manuelle
└── MISTRAL_SETUP.md        ← Config Mistral
```

---

## 🔧 Tag Git + Push

```bash
cd D:\Projets\PlanetDIag
git tag -a v1.2.2 -m "Release v1.2.2 — Intégration Mistral AI"
git push origin main
git push origin v1.2.2
```

---

## 📝 Description Release GitHub

```markdown
## PlanetDiag v1.2.2 — Analyse IA avec Mistral

**Nouvelle fonctionnalité majeure :** Après chaque diagnostic, générez automatiquement un audit IA complet avec Mistral Large.

### Highlights

🤖 **Analyse IA Mistral**
- Audit complet du système Windows
- Commandes exactes à exécuter
- Prompt expert : réparations + optimisations
- 20k tokens pour exhaustivité

🎨 **UI Améliorations**
- Démarrage en mode maximisé
- Panneau Mistral intégré
- Popup d'attente non-bloquant
- Layout corrigé

🔧 **Bugs Fixes**
- Exceptions Mistral correctes
- Markdown converter réécrit
- CSS valide, liens fixed

### Installation

**Exe seul** : `PlanetDiag.exe` (contient toutes les dépendances)

**Première utilisation** :
1. Générez une clé API Mistral (gratuit sur https://console.mistral.ai)
2. Collez-la dans le panneau IA (onglet Analyse)
3. Cliquez "Tester la clé"

### Tarification

~€0.004 par diagnostic (Mistral Large)

### Documentation

- 📖 **RELEASE_NOTES_v1.2.2.md** : guide complet
- 🔧 **MISTRAL_SETUP.md** : installation Mistral
- 📚 **CHANGELOG.md** : historique du projet

### SHA-256
```
[À remplir après build]
```

**Première release stable avec IA!** 🎉
```

---

## ⚠️ Validations Finales

- ✅ Exe exécutable (pas d'erreurs de dépendances)
- ✅ Interface démarrage maximisé
- ✅ Onglet Analyse : boutons + panneau Mistral visibles
- ✅ Tous les onglets accessibles (pas de crash)
- ✅ Hash SHA-256 calculé
- ✅ Taille de l'exe documentée
- ✅ Git tag créé et pushé

---

## 🚀 Post-Release

1. Créer la release sur GitHub avec l'exe et les notes
2. Annoncer sur les canaux de communication
3. Nettoyer les vieux builds dans `dist/`
4. Préparer v1.2.3 (placeholder pour prochain work)

---

**Statut :** Prêt à builder et uploader ✅
