# PlanetDiag v1.2.2 — Notes de Release

**Date de sortie :** 2025-06-03  
**Version précédente :** 1.2.1

---

## 🤖 Nouvelle Fonctionnalité : Analyse IA Mistral

### Qu'est-ce que c'est ?
Après chaque diagnostic, PlanetDiag peut maintenant générer un **audit IA complet** en utilisant **Mistral Large**. Cette analyse transforme les données techniques en **recommandations concrètes et actionnables** avec des commandes exactes à exécuter.

### Comment l'utiliser

1. **Configuration de la clé API**
   - Ouvrez PlanetDiag
   - Allez à l'onglet **"Analyse"** (onglet principal)
   - Dans le panneau "🤖 Analyse IA Mistral (optionnel)", entrez votre clé API Mistral
   - Cliquez "Tester la clé" pour vérifier
   - La clé est sauvegardée automatiquement et **chiffrée**

2. **Lancer un diagnostic**
   - Le diagnostic s'exécute normalement (rapport HTML + JSON)
   - Une popup vous informe que Mistral analyse les données (peut prendre plusieurs minutes)
   - Un second rapport HTML est généré : `PlanetDiag_MACHINE_TIMESTAMP_AI_ANALYSIS.html`
   - Le rapport s'ouvre automatiquement dans votre navigateur

3. **Rapport IA**
   - Audit complet du système
   - **Problèmes identifiés** avec cause et impact
   - **Commandes exactes** à exécuter (cmd, PowerShell, regedit)
   - **Optimisations** avec gains estimés
   - **Sécurité** : points à corriger
   - **Maintenance préventive** : séquence de commandes copy-paste

### Installation de la clé API Mistral

1. Créez un compte sur [Mistral AI Console](https://console.mistral.ai)
2. Générez une clé API dans les paramètres
3. Entrez-la dans PlanetDiag (elle est chiffrée avant sauvegarde)

**Tarification :** ~€0.004 par diagnostic (avec Mistral Large)

### Fonctionnalités techniques

- ✅ **20 000 tokens max** en sortie — audit exhaustif sans troncature
- ✅ **Temperature 0.2** — réponses factuelles et précises
- ✅ **Prompt chirurgical** — interdiction des conseils vagues, commandes obligatoires
- ✅ **Chiffrement Fernet** — clé API sécurisée (AES-128)
- ✅ **Popup non-bloquant** — l'UI reste libre pendant la génération
- ✅ **Fallback gracieux** — fonctionalité désactivée proprement si dépendances manquantes

---

## 🎨 Améliorations UI

- ✅ **Démarrage en mode maximisé** — tout le contenu visible sans scroll
- ✅ **Taille de restauration intelligente** — 85% de l'écran quand vous réduisez
- ✅ **Panneau Mistral intégré** dans l'onglet Analyse
- ✅ **Boutons et checkbox visibles** — layout corrigé

---

## 🔧 Corrections de Bugs

- ✅ Fix : exceptions Mistral avalées (ValueError -> RuntimeError)
- ✅ Fix : convertisseur Markdown cassé (listes détruites, code ignoré)
- ✅ Fix : bloquage UI pendant test clé API
- ✅ Fix : CSS invalide et liens morts
- ✅ Fix : test clé découplé de cryptography (requests seul suffit)

---

## 📦 Dépendances Nouvelles

| Package | Version | Raison |
|---------|---------|--------|
| `requests` | ≥2.25 | Appels API Mistral |
| `cryptography` | ≥3.4 | Chiffrement clé API |

Installées automatiquement lors de la compilation (build.bat).

---

## 📖 Documentation

Consultez **MISTRAL_SETUP.md** pour :
- Installation détaillée des dépendances
- Configuration clé API
- Dépannage complet
- Tarification et limites
- Bonnes pratiques de sécurité

---

## ✅ Vérification Pré-Release

- ✅ Tous les imports compilent (py -m py_compile)
- ✅ Markdown converter testé (titres, listes, code, XSS)
- ✅ Report generation testé (fichier créé, valide)
- ✅ Chiffrement round-trip testé
- ✅ Build.bat installe les dépendances

---

## 🚀 À Savoir Avant le Déploiement

1. **Première utilisation** : l'utilisateur doit avoir une clé API Mistral (gratuit jusqu'à certains crédits)
2. **Temps de génération** : 2-5 minutes selon la taille du diagnostic
3. **Sans dépendances** : si `requests` ou `cryptography` manquent, la feature se désactive proprement avec un message clair
4. **Chiffrement** : la clé API est stockée de manière sécurisée (AES-128), jamais en clair

---

## 📝 Historique des Commits

```
a86397c feat(ui): démarrage en mode maximisé + taille de restauration adaptative
c58860e feat(ui): popup d'attente non bloquant pendant l'analyse Mistral
36436f1 feat(mistral): prompt chirurgical + 20k tokens + temperature 0.2
7ae482d fix(mistral): découpler le test de clé de _HAS_MISTRAL
5f79f38 fix(ui): boutons + panneau Mistral masqués par le log expand=True
e108d89 feat(mistral): max_tokens 4096 -> 15000 + timeout 90s -> 240s
004b791 fix(mistral): corrections revue senior sur l'intégration IA
8a53834 refactor: Suppression import sys non utilisé
af96230 docs: Guide de configuration Mistral AI pour PlanetDiag
06ce810 feat(ai-analysis): Intégration Mistral AI pour l'analyse diagnostique
```

---

## ⬇️ Téléchargement

- **Exe** : `PlanetDiag.exe`
- **Sha256** : 0A600601FE35798708D520054884077E06361B0BB96184BEABDEF30017C46B18
- **Taille** : 19,1 mo
---
