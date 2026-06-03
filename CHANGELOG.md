# Changelog — PlanetDiag

Toutes les modifications notables de ce projet sont documentées ici.

---

## [1.2.2] — 2025-06-03

### ✨ Nouvelles Fonctionnalités

- **Analyse IA Mistral** : après chaque diagnostic, génération automatique d'un audit IA complet avec Mistral Large
  - Interface clé API dans l'onglet Analyse (clé chiffrée AES-128)
  - Popup d'attente non-bloquant pendant la génération
  - Rapport HTML standalone avec conversion markdown
  - Prompt expert : commandes exactes, conseils actionnables, pas de généricités
  - 20k tokens max sortie + temperature 0.2 pour précision
  - Timeout 300s pour audits complets
  - Fallback gracieux si dépendances manquantes

### 🎨 Améliorations UI

- **Démarrage en mode maximisé** : tout le contenu visible dès l'ouverture
- **Taille de restauration intelligente** : 85% de l'écran quand réduit
- **Layout corrigé** : pannel Mistral + boutons maintenant visibles

### 🔧 Corrections

- Fix : exceptions Mistral avalées (ValueError re-raised correctement)
- Fix : convertisseur markdown cassé (listes et blocs de code recréés)
- Fix : test clé API bloquait l'UI (déporté en thread)
- Fix : CSS invalide et lien mort supprimés
- Fix : test clé découplé de cryptography (requests seul suffit)

### 📦 Dépendances Nouvelles

- `requests` ≥2.25 : appels API Mistral
- `cryptography` ≥3.4 : chiffrement clé API

### 📚 Documentation

- `MISTRAL_SETUP.md` : guide complet de configuration
- `RELEASE_NOTES_v1.2.2.md` : notes détaillées de cette release
- `requirements.txt` : déclaration des dépendances Python
- `build.bat` : updated avec pip install des dépendances + hidden-imports

---

## [1.2.1] — 2025-06-02

### 🔧 Corrections

- Refactor quality : correction ponctuelle issues détectées

### 📝 Notes

- Version de stabilisation avant v1.2.2

---

## [1.2.0] — 2025-05-16

### ✨ Nouvelles Fonctionnalités

- **Module Dépannage** : Spooler, Réseau, WiFi, Réparation système
- **Ghost Protocol UI** : palette de couleurs cohérente
- **Moniteur Temps Réel** : CPU, RAM, Disque I/O, Températures

### 🔧 Corrections

- Refactor parallélisation collectors
- Threading amélioré
- Modules correctifs netsh/PowerShell

---

## [1.1.0] — 2025-04-01

### ✨ Nouvelles Fonctionnalités

- Collecteur SMART (santé disques)
- Collecteur Réseau
- Collecteur Sécurité

### 📊 Rapports

- Format HTML + JSON
- Alertes automatiques
- Statistiques détaillées

---

## [1.0.0] — 2025-03-01

### 🎉 Initial Release

- Diagnostic système complet (8 collecteurs)
- Rapport HTML interactive
- Monitoring temps réel
- Exportation JSON

---

## Format des Commits

Ce projet suit [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) :

- `feat:` nouvelle fonctionnalité
- `fix:` correction de bug
- `refactor:` refactorisation sans changement fonctionnel
- `docs:` documentation
- `chore:` maintenance, build, dépendances
- `test:` tests
- `perf:` performance
