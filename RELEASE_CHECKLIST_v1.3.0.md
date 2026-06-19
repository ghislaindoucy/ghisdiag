# Release Checklist — Ghisdiag v1.3.0

**Date cible :** 2026-06-10  
**Statut :** ⚠️ Rebuild requis (bump 1.2.3 → 1.3.0 après le build de validation)

---

## ✅ Pré-Build

- ✅ Version bump : **1.2.3 → 1.3.0** (orchestrator.py, report/generator.py, version_info.txt, README, mistral_report.py)
- ✅ RELEASE_NOTES_v1.3.0.md créé
- ✅ CHANGELOG.md mis à jour
- ✅ Diagnostic validé via orchestrateur (8/8 collecteurs, faux positifs éliminés)
- ⬜ Git tag à créer : `v1.3.0`
- ⬜ Merge sur `main`

---

## 📋 À Faire Avant Build

1. **Rebuild** (le build de validation portait encore la version 1.2.3 dans les métadonnées)
   ```batch
   cd D:\Projets\PlanetDIag
   build.bat
   ```
   - Vérifie `dist/Ghisdiag.exe`
   - Clic droit → Propriétés → Détails : la version doit afficher **1.3.0.0**

2. **Tester l'exe produit (focus diagnostic)**
   - Lancer `dist/Ghisdiag.exe` **en administrateur**
   - Lancer un **diagnostic complet** → le rapport HTML s'ouvre
   - Vérifier la section **📋 Événements** : nouveaux tableaux **Plantages**, **WHEA**, **Disque**, **NTFS**, **Services**
   - Vérifier **Points d'attention** : pas de « démarrage lent » fantôme sur un PC sain
   - Lancer l'**Analyse IA** (clé Mistral) → l'audit cite des preuves, distingue correctif/optimisation

3. **Calculer le hash SHA-256**
   ```powershell
   Get-FileHash "dist\Ghisdiag.exe" -Algorithm SHA256 | Format-Table Hash
   ```
   - Copier dans RELEASE_NOTES_v1.3.0.md

4. **Noter la taille de l'exe**
   ```powershell
   (Get-Item "dist\Ghisdiag.exe").Length / 1MB
   ```

---

## 🔧 Tag Git + Push

```bash
cd D:\Projets\PlanetDIag
git push origin main
git tag -a v1.3.0 -m "Release v1.3.0 — Diagnostic de fiabilité (logs L3), garde-fous faux positifs & prompt IA précis"
git push origin v1.3.0
```

---

## 📝 Description Release GitHub

```markdown
## Ghisdiag v1.3.0 — Diagnostic de fiabilité & IA précise

Ghisdiag détecte enfin les vrais incidents (BSOD, matériel, disque, NTFS, services)
et arrête les faux positifs. L'analyse IA diagnostique sur preuves.

### Highlights

🆕 **Logs niveau 3**
- Plantages/BSOD (code BugCheck), erreurs matérielles WHEA, disque, NTFS, services

🛡️ **Moins de faux positifs**
- « Démarrage lent » seulement au-delà de 60 s, fin du comptage fantôme, bruit updaters filtré

🤖 **Analyse IA**
- Preuve obligatoire par problème, seuils de référence, correctif/optimisation/surveillance

### Installation

**Exe seul** : `Ghisdiag.exe` (toutes dépendances embarquées)

### SHA-256
```
dbd553da51d9a51bc6a18997ad87140fe4cdf5a5760bd2e23761a5c96b4722d7
```
```

---

## ⚠️ Validations Finales

- ✅ Collecteurs PowerShell parsent + s'exécutent
- ✅ Python compile (orchestrator, generator, mistral_analyzer)
- ⬜ Exe rebuild en 1.3.0 et exécutable
- ⬜ Section Événements : nouveaux journaux visibles
- ⬜ Hash SHA-256 calculé
- ⬜ Git tag créé et pushé

---

## 🚀 Post-Release

1. Créer la release sur GitHub avec l'exe et les notes
2. Nettoyer les vieux builds dans `dist/`
3. Préparer la suite (températures CPU/GPU, pilotes obsolètes — cf. roadmap)

---

**Statut :** Rebuild en 1.3.0 puis tag & upload
