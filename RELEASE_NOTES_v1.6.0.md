# Ghisdiag v1.6.0 — Notes de Release

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
- **5 fournisseurs disponibles** : **Anthropic** (Claude Opus 4.8), **Mistral** (Large),
  **OpenAI** (GPT-5.5), **Grok** (xAI, Grok 4.3) et **Google** (Gemini 2.5 Pro).
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
- **Trois familles d'API** couvrent les fournisseurs : **OpenAI-compatible**
  (Mistral, OpenAI, Grok), **Anthropic** (`/v1/messages`) et **Gemini**
  (`generateContent`). Le chemin OpenAI-compatible est paramétré par fournisseur
  (champ `max_completion_tokens` pour GPT-5/Grok, `temperature` réservé aux modèles
  qui l'acceptent).
- **Réglages par fournisseur** : timeout et `reasoning_effort` ajustables. OpenAI
  (gpt-5.5, modèle de raisonnement) tourne en effort « low » avec un timeout élargi
  (600 s) pour éviter une expiration sur les audits longs en non-streaming.

### Migration transparente

- L'ancienne clé Mistral est **conservée et réutilisée** automatiquement : si elle
  existe, Mistral reste le fournisseur actif au premier lancement.

---

## 🌡️ Aussi dans cette version — bench thermique

- **Avertissement de responsabilité** avant chaque test : les sécurités (arrêt
  automatique à 95 °C, arrêt manuel) réduisent mais n'éliminent pas le risque ;
  selon l'état du matériel (poussière, pâte dégradée, ventilateur/capteur défaillant,
  composants fragilisés) un dommage reste possible. Le test démarre sous la
  responsabilité de l'utilisateur — Ghisdiag et son auteur dégagés de toute
  responsabilité.
- **Durée de charge personnalisable** : en plus des presets (Court / Standard / Long),
  une option « Personnalisé… » accepte une durée en minutes (1 à 30). La comparaison
  avant / après reste protégée par l'exigence d'un protocole identique (même durée et
  même intensité des deux côtés).

---

## ✅ Vérification Pré-Release

- ✅ `ai_analyzer.py`, `ai_report.py`, `prefs.py`, `main.py` compilent
- ✅ Smoke test UI : fenêtre « Configurer l'IA », bascule de fournisseur, libellé modèle
- ✅ Appels **Anthropic** et **Mistral** validés en conditions réelles (clé valide
  → audit généré) ; OpenAI / Grok / Gemini validés au niveau code (payloads, URL,
  routage par famille d'API)
- ✅ Génération du rapport HTML d'analyse (markdown → HTML, fournisseur/modèle indiqués)
- ✅ Chiffrement/déchiffrement des clés + migration de `mistral_api_key`
- ✅ Bench thermique : durée personnalisée (presets + custom) et avertissement vérifiés
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
feat(ia): branche OpenAI, Grok et Gemini (5 fournisseurs)
fix(ia): OpenAI gpt-5.5 timeout — reasoning_effort low + timeout 600s
feat(thermal): avertissement de responsabilite avant le bench
feat(thermal): duree de charge personnalisable
```

---

## ⬇️ Téléchargement

- **Exe** : `Ghisdiag.exe`
- **Sha256** : _à compléter après build_
- **Taille** : _à compléter après build_
