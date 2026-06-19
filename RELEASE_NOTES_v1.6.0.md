# PlanetDiag v1.6.0 — Notes de Release

**Date de sortie :** 2026-06-19  
**Version précédente :** 1.5.0

---

> Release **analyse IA multi-fournisseurs** : l'audit IA généré après un diagnostic
> n'est plus verrouillé sur Mistral. Choisissez votre fournisseur (Anthropic / Claude
> ou Mistral), saisissez votre clé, et obtenez le même audit expert quel que soit le
> modèle.

---

## 🤖 Analyse IA multi-fournisseurs

L'analyse IA optionnelle (déclenchée après un diagnostic si une clé est renseignée)
gagne une **fenêtre de configuration dédiée** et le choix du fournisseur.

### Choix du fournisseur

- Un bouton **« Configurer l'IA… »** ouvre une fenêtre : menu déroulant du
  fournisseur, champ de clé API (masqué), modèle utilisé affiché, et un bouton
  **« Tester la clé »** qui valide la clé en direct.
- Fournisseurs disponibles : **Anthropic (Claude Opus 4.8)** et **Mistral (Large)**.
- **Une clé API par fournisseur**, chacune **chiffrée** (Fernet, comme auparavant).
  Le fournisseur actif est mémorisé.

### Un seul prompt, pour tous les modèles

- Le **prompt d'audit expert** (10 sections, garde-fous anti-faux-positifs, exigence
  de preuves et de commandes prêtes à copier-coller) est **mutualisé** : il est
  envoyé à l'identique quel que soit le fournisseur. La qualité de l'audit ne dépend
  pas du modèle choisi.

### Moteur léger, sans SDK

- Tout passe par des appels **HTTP bruts en `requests`** — **aucun SDK** ajouté
  (`anthropic`, `openai`…), pour garder l'exécutable compact.
- Deux familles d'API couvrent les fournisseurs : **OpenAI-compatible**
  (Mistral, et plus tard OpenAI / Grok) et **Anthropic** (`/v1/messages`).
  Architecture extensible (OpenAI / Grok / Gemini prévus).

### Migration transparente

- L'ancienne clé Mistral est **conservée et réutilisée** automatiquement : si elle
  existe, Mistral reste le fournisseur actif au premier lancement.

---

## ✅ Vérification Pré-Release

- ✅ `ai_analyzer.py`, `ai_report.py`, `prefs.py`, `main.py` compilent
- ✅ Smoke test UI : fenêtre « Configurer l'IA », bascule de fournisseur, libellé modèle
- ✅ Appel **Anthropic** validé en conditions réelles (clé valide → audit généré)
- ✅ Génération du rapport HTML d'analyse (markdown → HTML, fournisseur/modèle indiqués)
- ✅ Chiffrement/déchiffrement des clés + migration de `mistral_api_key`
- ✅ Versions synchronisées (orchestrator, generator, version_info, manifest, README)

---

## 🚀 À Savoir Avant le Déploiement

1. **Confidentialité** : lancer l'analyse IA transmet les données du diagnostic à
   l'API du fournisseur choisi (déjà le cas avec Mistral). La fenêtre de
   configuration le rappelle.
2. **Aucune nouvelle dépendance Python** : `requests` et `cryptography` étaient déjà
   requis pour la fonctionnalité IA.
3. Les anciens modules `mistral_analyzer.py` / `mistral_report.py` sont remplacés par
   `ai_analyzer.py` / `ai_report.py`.

---

## 📝 Modifications

```
feat(ia): analyse IA multi-fournisseurs (Anthropic + Mistral)
release: bump version 1.6.0 (orchestrator, generator, version_info, manifest, README, CHANGELOG, ROADMAP)
```

---

## ⬇️ Téléchargement

- **Exe** : `PlanetDiag.exe`
- **Sha256** : _à compléter après build_
- **Taille** : _à compléter après build_
