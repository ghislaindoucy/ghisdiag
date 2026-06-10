# Changelog — PlanetDiag

Toutes les modifications notables de ce projet sont documentées ici.

---

## [1.2.3] — 2026-06-10

### ✨ Nouvelles Fonctionnalités

- **Onglet PC Neuf — VLC media player** : ajouté au catalogue des logiciels installables en silence via winget (`VideoLAN.VLC`)
- **Onglet PC Neuf — Icônes du bureau** : nouveau bouton « Ajouter les icônes du bureau » qui affiche en un clic :
  - **Ce PC** `{20D04FE0-…}`
  - **Fichiers de l'utilisateur** `{59031a47-…}`
  - **Corbeille** `{645FF040-…}` (si elle n'est pas déjà présente)
  - Application via le registre `HideDesktopIcons\NewStartPanel` + rafraîchissement du shell (`SHChangeNotify`), sans redémarrer l'explorateur

### 🔧 Corrections

- **Fix winget « fichier introuvable » en contexte admin** : `Get-WingetPath` résout désormais le **vrai** `winget.exe` en testant réellement chaque candidat (package AppX, `Program Files\WindowsApps`, commande nue), au lieu de retourner aveuglément le stub d'alias 0 octet qui échouait à l'exécution — corrigé dans `setup_apps.ps1` **et** `winget_manager.ps1` (onglet Mises à jour)
- **Fix détection « déjà installé »** : la vérification interroge chaque application par son **ID exact** (`winget list --id … --exact`), éliminant les faux « non installé » dus à la troncature de la colonne Id en sortie redirigée
- **Retour visuel de la vérification** : statut explicite « ✓ Installé » / « ✗ Non installé » par application + messages de progression et de fin dans le journal

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
