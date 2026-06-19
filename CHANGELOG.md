# Changelog — PlanetDiag

Toutes les modifications notables de ce projet sont documentées ici.

---

## [1.6.0] — 2026-06-19

### 🤖 Analyse IA multi-fournisseurs

L'analyse IA n'est plus verrouillée sur Mistral : choisissez votre fournisseur et
saisissez votre clé via une fenêtre de configuration dédiée.

- **5 fournisseurs au choix** : **Anthropic** (Claude Opus 4.8), **Mistral** (Large),
  **OpenAI** (GPT-5.5), **Grok** (xAI, Grok 4.3) et **Google** (Gemini 2.5 Pro),
  sélectionnés dans une fenêtre « Configurer l'IA » (menu déroulant, clé API par
  fournisseur, bouton « Tester la clé »)
- **Prompt d'audit mutualisé** : le même prompt expert (10 sections, garde-fous
  anti-faux-positifs) est réutilisé à l'identique quel que soit le fournisseur —
  la qualité ne dépend pas du modèle
- **Moteur léger en `requests` brut** (aucun SDK ajouté, l'exe reste compact) :
  trois familles d'API couvrent les fournisseurs (OpenAI-compatible pour
  Mistral/OpenAI/Grok, Anthropic, Gemini), paramétrées par fournisseur
- **Clés chiffrées par fournisseur** (Fernet, comme avant) + migration automatique
  de l'ancienne clé Mistral
- Rapport HTML d'analyse générique (fournisseur et modèle indiqués)

## [1.5.0] — 2026-06-18

### 🌡️ Bench thermique avant / après maintenance

Nouvel onglet **« Bench thermique »** pour objectiver le gain d'un nettoyage ou d'un
changement de pâte thermique — un argument concret à montrer au client.

- **Source de températures fiable** : embarque **LibreHardwareMonitorLib** (MPL-2.0)
  + le driver **PawnIO** (signé, hors blocklist Win11) pour lire température et
  fréquence CPU via les MSR. Remplace la chaîne WMI/OHM fragile (souvent vide sur
  desktop). Bénéfice immédiat : le moniteur temps réel affiche enfin des
  températures partout (CPU/GPU/disques/ventilateurs)
- **Moteur de bench** (`thermal_bench.py`) : protocole repos → charge CPU →
  refroidissement, durées et intensité (50/100 %) configurables. Génération de
  charge par workers PowerShell (runspaces .NET, un par cœur). **Arrêt d'urgence
  automatique à 95 °C**. Métriques : T repos/max/plateau, ΔT, temps de retour au
  calme, **détection de throttling**, vitesses ventilateurs. Sessions enregistrées
  en JSON horodaté (avant/après/libre)
- **Graphe temps réel** sur `tk.Canvas` (zones colorées par phase, courbes
  CPU/GPU/disque, ligne d'urgence 95 °C) — sans matplotlib, l'exe reste léger
- **Comparaison avant / après** (`thermal_compare.py`) : courbes superposées,
  carte des gains (ΔT, plateau, max, retour au calme, throttling éliminé) et
  **rapport HTML autonome** (courbes SVG, hors-ligne, imprimable) avec verdict
  clair pour le client. Garde-fou honnêteté : protocoles identiques exigés, et le
  ΔT (insensible à l'ambiant) est mis en avant comme mesure fiable

### ✨ Nouvelles Fonctionnalités

- **Renommer un compte utilisateur local** (onglet ⚙️ Setup) : nouvelle section « ✏️ Renommer un compte » — sélection d'un compte existant, saisie du nouveau nom, application via `Rename-LocalUser`. Le profil et les données sont conservés (SID inchangé)
  - Action `rename-user` ajoutée à `collectors/user_manager.ps1`, avec garde-fous : validation du nom (mêmes règles que la création), compte source existant, nouveau nom libre et différent de l'ancien

---

## [1.4.0] — 2026-06-11

### 🎨 Refonte Graphique — Thème Catppuccin Mocha Unifié

- **Nouvelle palette** : abandon du thème néon « Ghost Protocol » (cyan électrique sur noir) au profit de **Catppuccin Mocha**, déjà utilisée par le rapport HTML — identité visuelle unifiée entre l'application, le rapport diagnostic et le rapport Mistral, contraste élevé (texte principal AAA), couleurs pastel reposantes
- **Typographie** : interface en Segoe UI (titre en Semibold), Consolas réservé aux données et journaux ; tailles minimales remontées de 8 pt à 9 pt
- **Barre de titre Windows sombre** (DWM immersive dark mode) — fini le bandeau blanc
- **Widgets harmonisés** : 18 scrollbars natives claires remplacées par des `ttk.Scrollbar` thémées, séparateurs blancs remplacés par des lignes discrètes, liste déroulante des comptes aux couleurs du thème, suppression des anneaux de focus clairs (Listbox/Text/Entry)
- **Constantes hover** (`ACCENT_HOVER`, `RED_HOVER`…) : plus aucune couleur codée en dur dans les widgets

### 🤖 Analyse IA Mistral — Audit Plus Profond

- **Nouveau bloc « Profondeur d'analyse »** dans le prompt : corrélations inter-sections obligatoires (événement disque ↔ SMART, crash ↔ driver…), analyse temporelle des événements répétés (compte, période, motif), cause racine en chaîne causale, niveau de confiance par diagnostic avec hypothèse alternative
- **Plan d'audit étendu de 7 à 10 sections** : fiche d'identité du poste, revue domaine par domaine (y compris les domaines sains, avec valeurs chiffrées), points de surveillance (le niveau SURVEILLANCE n'avait pas de section), matériel étendu à la projection durée de vie/usure
- **Garde-fous anti-faux-positifs conservés** : plus de détails ne veut jamais dire plus d'alertes — la richesse est dans le descriptif et les corrélations
- **Tableaux markdown interdits** dans la réponse IA (non supportés par le rendu du rapport Mistral) au profit de listes structurées

---

## [1.3.0] — 2026-06-10

### ✨ Nouvelles Fonctionnalités

- **Diagnostic de fiabilité — journaux niveau 3** ajoutés dans `collectors/events.ps1` :
  - **Plantages & redémarrages inattendus** (`crash_events`) : Kernel-Power ID 41, BugCheck ID 1001 (avec extraction du **code BSOD** `0x…`), arrêt inattendu 6008 — sur 14 jours
  - **Erreurs matérielles WHEA** (`whea_events`) : journal `Microsoft-Windows-WHEA-Logger`, erreurs CPU/RAM/PCIe corrigées (Warning) ou non corrigées (Error) sur 30 jours
  - **Erreurs disque** (`disk_events`) : provider `disk` IDs 7/11/51/153 (E/S, secteurs défectueux, timeouts contrôleur) sur 14 jours
  - **Corruption NTFS** (`ntfs_events`) : `Microsoft-Windows-Ntfs` IDs 55/57/98/137 sur 14 jours
  - **Services en échec** (`scm_events`) : `Service Control Manager` IDs 7000/7009/7011/7031/7034… sur 7 jours
- **Analyse fiabilité** (`_analyse_reliability`) : nouvelles alertes BSOD, redémarrage inattendu, WHEA, disque, NTFS, services — avec sévérité graduée
- **Section HTML enrichie** : bannière fiabilité, carte « Plantages (14j) » et tableaux de détail par journal

### 🛡️ Moins de Faux Positifs

- **Démarrage lent** : l'événement Diagnostics-Performance ID 100 étant émis à *chaque* démarrage, l'alerte ne se déclenche désormais qu'au-delà d'un **seuil réel** (`SLOW_BOOT_MS = 60 s`, via MainPathBootTime) au lieu de se déclencher systématiquement
- **Bug de comptage fantôme corrigé** : une collection vide retournée par PowerShell se sérialise en `{}`, que `_ensure_list` transformait en `[{}]` (un élément fantôme) → fausses alertes « 1 événement ». Corrigé au point central, pour **tous** les collecteurs
- **Bruit des updaters tiers** : les échecs de service récurrents de Google/Edge Update sont filtrés et dédupliqués (plus d'alerte « services en échec » trompeuse)

### 🤖 Analyse IA Mistral — Précision

- **Prompt refondu** autour de la rigueur : **preuve obligatoire** (section + ID/valeur) pour chaque problème, **seuils de référence** fournis (RAM < 75 %, boot < 60 s, Defender off + AV tiers actif = normal…)
- Distinction explicite **CORRECTIF / OPTIMISATION / SURVEILLANCE** ; interdiction d'inventer un problème pour remplir le plan ; section « problèmes » conditionnelle (« Aucun problème avéré détecté »)
- **Payload JSON compact** (sans indentation) : le rapport complet tient dans la fenêtre contexte sans troncature des sections utiles

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
