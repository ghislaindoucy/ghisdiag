# 🔍 Ghisdiag

> **Diagnostic Windows professionnel + Analyse IA.** Découvrez tous les soucis de votre PC en 2 clics, puis laissez l'IA de votre choix (Claude, Mistral, GPT, Grok ou Gemini) vous générer un plan d'action détaillé.

[![Version](https://img.shields.io/badge/version-2.1.0-blue.svg)](https://github.com/ghislaindoucy/ghisdiag/releases/tag/v2.1.0)
[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial-orange.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)]()
![Windows Only](https://img.shields.io/badge/platform-Windows%20Only-0078D4.svg)

---

## ✨ Ce que tu peux faire avec Ghisdiag

### 🚀 Diagnostic complet en moins de 5 minutes

- **Système & Matériel** — CPU, RAM, disques, température, BIOS
- **Performance** — Charge système, processus lourds, fragmentation
- **Démarrage Windows** — Services auto, programmes de démarrage (lents!)
- **Événements système** — Erreurs, avertissements (dernières 72h)
- **Fiabilité** — Plantages (BSOD/BugCheck), erreurs matérielles WHEA, corruption NTFS, services en échec
- **Réseau** — Connexion, DNS, pare-feu, VPN
- **Sécurité** — Mises à jour, antivirus, UAC, historique login
- **Logiciels & Drivers** — Drivers cassés, applications obsolètes
- **Santé disques** — SMART monitoring (SSD/HDD)

### 🌡️ Bench thermique avant / après maintenance

- Protocole guidé : repos → charge CPU → refroidissement, courbes en temps réel
- Températures fiables via LibreHardwareMonitor + driver PawnIO (CPU/GPU/disques/ventilateurs)
- Détection de throttling, arrêt d'urgence à 95 °C, durée de charge personnalisable
- Comparaison avant/après superposée + rapport HTML imprimable avec verdict client

### 🛠️ Dépannage & PC Neuf

- **Réparation système** — SFC, DISM, vidage des journaux Windows pour une base de test propre
- **PC Neuf** — installation en 1 clic de logiciels essentiels (via winget), icônes du bureau

### 🕒 Heure & veille (onglet Setup / MAJ, en tête)

- **Mise à l'heure** — synchronisation Internet (NTP) **ou** saisie manuelle pour une machine sans réseau, plus le choix du fuseau horaire
- **Blocage de la mise en veille** pendant une intervention longue — activé automatiquement par le bench thermique le temps du test

### 🤖 Analyse IA multi-fournisseurs

Après ton diagnostic, active l'analyse IA et choisis ton fournisseur — **Anthropic (Claude Opus 4.8)**, **Mistral (Large)**, **OpenAI (GPT-5.5)**, **Grok (xAI 4.3)** ou **Google (Gemini 2.5 Pro)** — pour obtenir :
- ✅ **Audit complet** — ce qui va pas, ce qui peut s'améliorer (avec preuve par problème)
- ✅ **Commandes exactes** — copie-colle direct dans PowerShell/CMD
- ✅ **Plan de réparation** — étapes détaillées pour chaque problème
- ✅ **Optimisations** — gagner en vitesse et stabilité
- ✅ **Priorités claires** — critique → grave → moyen → faible

Clé API par fournisseur (chiffrée AES-128), boutons « Tester la clé » et « Éjecter la clé », aucun SDK requis.

---

## 🎯 Commencer en 30 secondes

### 1️⃣ Télécharge et lance
```bash
# Récupère Ghisdiag.zip depuis les releases, décompresse-le,
# puis double-clique sur Ghisdiag.exe dans le dossier obtenu
```

### 2️⃣ Clique sur "Lancer le diagnostic"
- Attends ~3-5 minutes
- Reçois un rapport HTML complet

### 3️⃣ (Optionnel) Active l'analyse IA
- Ouvre « 🤖 Configurer l'IA » et choisis ton fournisseur (Claude, Mistral, GPT, Grok ou Gemini)
- Colle ta clé API et teste-la
- Relance un diagnostic → rapport IA automatique

**C'est tout!** 🎉

---

## 📦 Installation

### Windows (archive portable)
1. Télécharge `Ghisdiag.zip` depuis les [releases](https://github.com/ghislaindoucy/ghisdiag/releases)
2. Décompresse-le où tu veux — disque local, ou directement sur une clé USB
3. Double-clique sur `Ghisdiag.exe` dans le dossier obtenu
4. Accepte les droits administrateur
5. C'est parti!

**Prérequis :** Windows 10/11, rien d'autre (tout est embarqué dans le dossier)

La **notice d'utilisation** (`Notice_Ghisdiag.pdf`) est livrée dans le dossier, à
côté de `Ghisdiag.exe` — plus besoin d'aller la chercher sur le dépôt.

> ℹ️ Garde le dossier entier : `Ghisdiag.exe` a besoin du sous-dossier `_internal\`
> posé à côté de lui. Ce format évite de décompresser 34 Mo dans le `%TEMP%` de
> chaque machine à chaque lancement — c'est plus rapide en usage nomade, ça ne
> laisse aucune trace chez le client, et c'est moins signalé par les antivirus
> (voir [docs/antivirus-guide.md](docs/antivirus-guide.md)).

### Développement (depuis le code source)
```bash
git clone https://github.com/ghislaindoucy/ghisdiag.git
cd ghisdiag

# Installe les dépendances
pip install -r requirements.txt

# Lance l'app
python main.py
```

---

## 🔌 Configuration Mistral IA (optionnel)

Veux tu que Ghisdiag génère des audits IA ?

1. **Crée un compte** : https://console.mistral.ai (gratuit)
2. **Génère une clé API** dans les paramètres
3. **Colle-la dans Ghisdiag** → onglet Analyse → panneau IA
4. **Teste** → clic sur "Tester la clé"
5. **C'est bon!** Le prochain diagnostic lancera auto l'IA

👉 **Lire [MISTRAL_SETUP.md](./MISTRAL_SETUP.md) pour plus de détails.**

---

## 📊 Exemple de sortie

### Rapport Technique (automatique)
```
Ghisdiag_LAPTOP-ABC_20250603_143056.html
├── Alertes détectées (RAM à 92%, driver obsolète)
├── Statistiques système (graphiques)
├── Historique des erreurs
└── Recommandations
```

### Rapport IA Mistral (optionnel)
```
Ghisdiag_LAPTOP-ABC_20250603_143056_AI_ANALYSIS.html
├── Résumé exécutif
├── Problèmes rangés par priorité
├── **Commandes exactes à exécuter**
├── Étapes de réparation détaillées
├── Optimisations + gains estimés
└── Recommandations matériel
```

---

## 🎨 Interface

- **Thème Catppuccin Mocha** — UI sombre unifiée entre l'app et les rapports
- **Logo chat & branding** — icône dédiée en en-tête et dans la barre des tâches
- **Mode maximisé au démarrage** — tout le contenu visible
- **Moniteur temps réel** — CPU/RAM/Disque/Température en direct
- **Journal d'activité live** — suivi de chaque opération
- **Rapport HTML interactif** — à partager, à archiver
- **Notice d'utilisation PDF** — guide illustré, glossaire et configuration des clés API

---

## 📝 Changelog

### v2.1.0 (Août 2026)
⚙️ **Setup / MAJ passe en premier onglet, et sait régler l'heure**
- **« Setup / MAJ » en tête** — c'est l'onglet du premier geste sur une machine fraîchement réinstallée ; il était le dernier. L'application s'ouvre désormais dessus.
- **Nouveau sous-onglet « Heure & veille »** — horloge vivante, fuseau actif, source de temps et état du service W32Time. Une horloge fausse fait échouer winget, l'activation Windows et toute connexion HTTPS.
- **Deux chemins pour la mise à l'heure** : synchronisation Internet (NTP) **ou** saisie manuelle. En atelier, la machine n'a souvent pas encore de réseau : la synchro n'est pas un passage obligé, et son échec renvoie explicitement vers la saisie manuelle. Choix du fuseau horaire dans la liste Windows complète.
- **Blocage de la mise en veille**, avec option « garder l'écran allumé ». **Le bench thermique l'active tout seul** : un test dure jusqu'à ~17 min sans interaction, et une machine qui s'endormait en pleine charge ruinait la mesure.
- 📖 La **notice PDF est maintenant livrée dans l'archive**, à côté de `Ghisdiag.exe`.
- 🩹 **Re-build du 07/08** (même numéro de version, archive remplacée — re-télécharge si tu l'avais déjà) : bouton **« Éjecter la clé »** pour retirer sa clé API d'un poste qu'on laisse chez un client ; le **renommage de compte change enfin le nom affiché par Windows** (écran de connexion, menu Démarrer) et plus seulement le nom interne ; choisir un dossier de destination n'efface plus les clés API enregistrées.

[📖 Notes complètes →](./RELEASE_NOTES_v2.1.0.md)

### v2.0.3 (Août 2026)
🌡️ **Le bench thermique ne conclut plus à partir d'un test incomplet**
- **Un test écourté ne dit plus « pas de throttling »**. Quand la charge est coupée avant son terme (arrêt d'urgence au seuil de sécurité), l'outil répondait « Throttling : non » — sur un HP Omen mesuré en atelier, après 23 s de charge sur 300 prévues. Il répond maintenant **indéterminé**, et explique la vraie cause : test trop court, ou fréquences illisibles sur cette machine.
- **La machine était-elle vraiment au repos ?** La température de repos est le point zéro de toute la mesure. Mesuré en atelier : 16,5 % de charge CPU pendant une phase censée être au repos — repos surévalué, ΔT sous-évalué, aucun avertissement. C'est désormais signalé, et une comparaison avant/après dont **une seule** des deux sessions est concernée ne chiffre plus de gain.
- **Une interruption des capteurs ne coûte plus le test entier.** Le moteur est relancé automatiquement ; une coupure pendant la charge arrête la charge par sécurité mais laisse mesurer le refroidissement. Les interruptions sont enregistrées dans la session.

[📖 Notes complètes →](./RELEASE_NOTES_v2.0.3.md)

### v2.0.2 (Juillet 2026)
🚨 **Correctif critique — les capteurs ne fonctionnaient pas après téléchargement**
- Toute personne ayant téléchargé l'archive depuis GitHub et décompressé avec l'Explorateur Windows n'avait **aucune température, aucun ventilateur, aucune fréquence**. Versions 2.0.0 et 2.0.1 concernées.
- **Cause** : Windows marque « vient d'Internet » chaque fichier extrait d'une archive téléchargée, et .NET refuse alors de charger les bibliothèques du moteur de capteurs. Le défaut est né du passage en dossier portable et échappait aux tests, qui partent de fichiers copiés — jamais marqués.
- **Correctif** : l'application retire la marque de ses propres bibliothèques avant de les charger. Plus besoin de « débloquer » l'archive.

[📖 Notes complètes →](./RELEASE_NOTES_v2.0.2.md)

### v2.0.1 (Juillet 2026)
🌡️ **Le bench thermique n'affirme plus ce qu'il n'a pas mesuré**
- **Throttling en trois états** — oui / non / **indéterminé**. Il se déduit d'une comparaison de fréquences ; sans fréquence exploitable, l'outil dit qu'il ne sait pas au lieu de répondre « non ». Les sessions déjà enregistrées sont relues correctement.
- **Fréquences CPU retrouvées sur les Intel récents** (12ᵉ génération et plus) : leurs capteurs se nomment `P-Core #N` / `E-Core #N`, Ghisdiag ne cherchait que `CPU Core #N` et n'en trouvait aucun — ce qui désactivait **silencieusement** toute la détection de throttling sur ces machines.
- **Plus de « plateau » sur une charge écourtée** : sur un test coupé avant terme, plateau et ΔT sont laissés vides plutôt qu'inventés à partir d'une simple montée en température.
- **Limite de puissance (PL1/TDP) enfin détectée** : un portable qui plafonne parce qu'il applique sa limite de puissance l'affiche désormais, au lieu de laisser croire à une surchauffe.
- **La comparaison avant/après vérifie les conditions de mesure** (noyau de charge, arrêt d'urgence, charge réellement tenue). Si elles diffèrent, le verdict ne chiffre plus de gain.
- 🩺 **Diagnostic** : la cause exacte d'un refus des capteurs remonte enfin jusqu'à l'utilisateur, et le journal indique au démarrage la version, l'élévation et le backend actif. Trois outils d'atelier ajoutés (`collectors/dump_sensors.ps1`, `dump_power_state.ps1`, `install_sensors_patch.ps1`).
- 🔧 Seuil d'arrêt d'urgence réglable par `GHISDIAG_EMERGENCY_TEMP_C` (60-99 °C).

[📖 Notes complètes →](./RELEASE_NOTES_v2.0.1.md)

### v2.0.0 (Juillet 2026)
📦 **Nouveau format de distribution — dossier portable**
- Ghisdiag se télécharge désormais en **archive `Ghisdiag.zip`** (~34 Mo, même taille qu'avant) à décompresser : un dossier contenant `Ghisdiag.exe` et son sous-dossier `_internal\`. **Garder le dossier entier.**
- **Pourquoi :** l'ancien exe unique décompressait 34 Mo dans le `%TEMP%` de la machine cliente **à chaque lancement** — lent en usage nomade, et il laissait des traces chez le client. Le nouveau format ne décompresse rien.
- 🛡️ **Moins de faux positifs antivirus** : ce schéma d'auto-extraction est celui des *droppers* et pesait lourd dans les scores heuristiques. S'y ajoutent la sauvegarde WiFi sans mots de passe en clair par défaut, l'abandon de la compression UPX, et un **build public vérifiable** (attestation de provenance SLSA via GitHub Actions).
- 🧹 **Correctifs** : une seule invite UAC au démarrage (le manifeste était inopérant, l'app se relançait elle-même), températures disque affichées dès l'ouverture du moniteur au lieu de 10 s d'attente, noms de profils lisibles à la restauration WiFi.
- 🔧 Nouveau commutateur `GHISDIAG_DEBUG=1` pour un journal détaillé — utile en atelier.

[📖 Notes complètes →](./RELEASE_NOTES_v2.0.0.md)

### v1.8.2 (Juillet 2026)
🤖 **Question libre à l'IA**
- **Champ question optionnel** (500 car.) dans le panneau Analyse IA : pose une question précise en rapport avec le poste, en plus de l'audit automatique
- La réponse arrive **en tête du rapport IA**, appuyée sur les données réelles du diagnostic ; garde-fou hors-sujet (question sans rapport = déclinée poliment)
- Visible seulement quand une clé API est configurée ; sans question, comportement inchangé
- 🩹 *Correctif (re-build du 24/07)* : bench thermique, la cible **GPU** pouvait rester bloquée sur « Détection des cartes graphiques en cours… » sur les machines NVIDIA — la détection se relance maintenant d'elle-même

[📖 Notes complètes →](./RELEASE_NOTES_v1.8.2.md)

### v1.8.1 (Juillet 2026)
🖥️ **Interface défilable sur petits écrans**
- **Tous les onglets défilables** (Analyse et Bench thermique rejoignent les autres) : plus aucun contenu coupé sur les portables 14" ou en mise à l'échelle Windows ; la barre n'apparaît qu'en cas de manque de place
- **En-tête compact** sur écran court + fenêtre restaurée bornée à l'écran
- Correctif molette (une seule zone captait le défilement de toute l'app)

[📖 Notes complètes →](./RELEASE_NOTES_v1.8.1.md)

### v1.8.0 (Juillet 2026)
🚦 **Diagnostic encore plus parlant**
- **Résumé exécutif « Ce qui ralentit ce PC »** : top 3 des freins de performance, priorisés, avec l'action à mener
- **Pilotes obsolètes ou non signés** signalés, avec la source de mise à jour
- **Démarrage lent décomposé phase par phase** + **comparaison de deux diagnostics dans le temps** (historique)

[📖 Notes complètes →](./RELEASE_NOTES_v1.8.0.md)

### v1.7.0 (Juillet 2026)
🎮 **Bench thermique GPU**
- Chauffe reproductible de la **carte graphique** (tous fabricants, sans rien installer), mesures fiables via le pilote NVIDIA
- Comparaison avant/après et rapport client dédiés au GPU
- Validé en atelier (RTX 4060, GTX 1060, GT 1030, Quadro P2000, AMD APU, Intel iGPU) — aucun plantage ni reset de pilote

[📖 Notes complètes →](./RELEASE_NOTES_v1.7.0.md)

### v1.6.6 (Juillet 2026)
♿ **Accessibilité petit écran**
- Interface utilisable sur **laptops à petit écran** et en **mise à l'échelle Windows 125 %/150 %** : plus aucun bouton ni contrôle coupé hors de la fenêtre
- Correctifs d'affichage uniquement — mise à jour recommandée pour les techniciens en atelier

[📖 Notes complètes →](./RELEASE_NOTES_v1.6.6.md)

### v1.6.5 (Juin 2026)
🌡️ **Capteurs & bench thermique fiables sur tout-terrain**
- Suivi de température **robuste sur n'importe quel CPU** (anti-freeze, GPU NVML + disques smartctl, mapping AMD Zen 5) ; température CPU **fluide** dans le moniteur temps réel
- Section **« Capteurs »** dans le rapport + raison affichée quand la température CPU manque (PawnIO/élévation)
- Bench thermique : **mode « Stabilité (AVX max) »** (vrai test de stress), distinction **throttling thermique** vs **limite de puissance (PL1/TDP)**, et corrections de fidélité

[📖 Notes complètes →](./RELEASE_NOTES_v1.6.5.md)

### v1.6.4 (Juin 2026)
🐛 **Correctif diagnostic**
- Fin du faux positif « Corruption NTFS » : l'événement de routine « volume sain » (NTFS 98) n'est plus compté comme une corruption

[📖 Notes complètes →](./RELEASE_NOTES_v1.6.4.md)

### v1.6.3 (Juin 2026)
⚖️ **Conformité licences tierces**
- Mentions légales complètes des composants tiers (THIRD-PARTY-NOTICES + textes de licence)
- Nouveau dialogue « Licences & mentions légales » accessible depuis l'en-tête de l'app
- Licences embarquées dans l'exe et attachées automatiquement aux releases

[📖 Notes complètes →](./RELEASE_NOTES_v1.6.3.md)

### v1.6.2 (Juin 2026)
🔗 **Accès au projet & documentation**
- Lien « Code source & releases sur GitHub » dans l'en-tête de l'application
- README à jour avec toutes les fonctionnalités actuelles (bench thermique, dépannage, fiabilité, IA multi-fournisseurs)

[📖 Notes complètes →](./RELEASE_NOTES_v1.6.2.md)

### v1.6.1 (Juin 2026)
🎨 **Finitions interface & branding**
- Le logo chat remplace l'ancienne planète dans l'en-tête de l'application
- Lien de soutien « ☕ Offrez-moi un café » (PayPal) dans l'en-tête, le README et la notice

🧹 **Base de test propre**
- Nouvelle option « Vider les journaux Windows » (onglet Dépannage → Réparation système)

📖 **Documentation**
- Notice d'utilisation illustrée au format PDF (toutes les fonctionnalités, glossaire, clés API)

[📖 Notes complètes →](./RELEASE_NOTES_v1.6.1.md)

### v1.6.0 (Juin 2026)
🤖 **Analyse IA multi-fournisseurs**
- 5 fournisseurs au choix via une fenêtre « Configurer l'IA » : Anthropic (Claude Opus 4.8), Mistral (Large), OpenAI (GPT-5.5), Grok (xAI, 4.3), Google (Gemini 2.5 Pro)
- Clé API par fournisseur (chiffrée), boutons « Tester la clé » et « Éjecter la clé », migration de l'ancienne clé Mistral
- Prompt d'audit expert mutualisé, moteur léger en `requests` (aucun SDK)

🌡️ **Bench thermique**
- Avertissement de responsabilité avant le test (le matériel peut être endommagé selon son état)
- Durée de charge personnalisable (presets + saisie libre en minutes)

[📖 Notes complètes →](./RELEASE_NOTES_v1.6.0.md)

### v1.5.0 (Juin 2026)
🌡️ **Bench thermique avant / après maintenance**
- Nouvel onglet : protocole repos → charge CPU → refroidissement, courbes en temps réel
- Températures fiables via LibreHardwareMonitor + driver PawnIO (CPU/GPU/disques/ventilateurs)
- Détection de throttling, arrêt d'urgence à 95 °C, sessions enregistrées
- Comparaison avant/après : courbes superposées + rapport HTML imprimable avec verdict client

[📖 Notes complètes →](./RELEASE_NOTES_v1.5.0.md)

### v1.4.0 (Juin 2026)
🎨 **Refonte graphique — Catppuccin Mocha**
- Thème sombre moderne unifié entre l'app et les rapports : contraste élevé, pastels lisibles
- Barre de titre Windows sombre, scrollbars et widgets entièrement thémés
- Typographie revue (Segoe UI pour l'interface, Consolas pour les données)

🤖 **Audit IA plus profond**
- Corrélations entre sections (disque ↔ SMART, crash ↔ driver), motifs temporels des événements
- Fiche d'identité du poste, revue domaine par domaine, points de surveillance, durée de vie matériel
- Niveau de confiance par diagnostic — toujours zéro problème inventé

[📖 Notes complètes →](./RELEASE_NOTES_v1.4.0.md)

### v1.3.0 (Juin 2026)
🆕 **Diagnostic de fiabilité (logs niveau 3)**
- Détection des **plantages** : écrans bleus (BSOD avec code BugCheck), redémarrages inattendus
- **Erreurs matérielles WHEA** (CPU/RAM/PCIe), **erreurs disque** (E/S) et **corruption NTFS**
- **Services en échec** (démarrage/timeout), filtrés du bruit des updaters tiers

🛡️ **Moins de faux positifs**
- Alerte « démarrage lent » seulement au-delà d'un seuil réel (60 s), plus à chaque boot
- Correction d'un bug de comptage fantôme (collections vides comptées comme 1 événement)

🤖 **Analyse IA plus précise**
- Prompt Mistral exigeant une **preuve** par problème + seuils de référence
- Distingue correctif / optimisation / surveillance, n'invente plus de problèmes
- Données envoyées en JSON compact (rapport complet, sans troncature)

[📖 Notes complètes →](./RELEASE_NOTES_v1.3.0.md)

### v1.2.3 (Juin 2026)
🆕 **Onglet PC Neuf enrichi**
- **VLC media player** ajouté aux logiciels installables
- **Icônes du bureau** en 1 clic : Ce PC, Fichiers utilisateur, Corbeille

🔧 **Fiabilité winget**
- Résolution robuste de `winget.exe` (fini le « fichier introuvable » en admin)
- Détection « déjà installé » par ID exact (plus de faux négatifs)
- Retour visuel clair lors de la vérification

[📖 Notes complètes →](./RELEASE_NOTES_v1.2.3.md)

### v1.2.2 (Juin 2025)
✨ **Analyse IA Mistral intégrée**
- Popup d'attente non-bloquant
- Conversion Markdown → HTML
- Commandes exactes, pas de conseils vagues
- Chiffrement clé API (AES-128)

🎨 **UI améliorations**
- Démarrage en mode maximisé
- Taille de restauration intelligente
- Layout corrigé (boutons maintenant visibles!)

🔧 **Corrections**
- Bugs Mistral fixes
- Markdown converter réécrit
- Dépendances correctement déclarées

[📖 Notes complètes →](./RELEASE_NOTES_v1.2.2.md)

---

## 🔒 Sécurité

- ✅ **Admin requis** — pas d'accès aux données sensibles sans droits
- ✅ **Clé API chiffrée** — jamais stockée en clair (AES-128 Fernet)
- ✅ **Clé API éjectable** — bouton « Éjecter la clé » : effacement du disque et de la mémoire avant de laisser l'appli sur un poste tiers
- ✅ **Pas de tracking** — tout reste local, aucun envoi de données
- ✅ **Exe signable** — prêt pour signature de code (optionnel)

---

## 🛠️ Build toi-même

```batch
cd D:\Projets\Ghisdiag
build.bat
```

Le build est piloté par `Ghisdiag.spec`, versionné dans le dépôt et partagé avec
l'intégration continue — toute option de compilation se change là, nulle part
ailleurs.

Deux sorties :
- `dist/Ghisdiag/` — le dossier à copier tel quel sur une clé USB (~78 MB, 1126 fichiers)
- `dist/Ghisdiag.zip` — l'archive à publier en release (~35 MB)

`docs/Notice_Ghisdiag.pdf` est copiée dans `dist/Ghisdiag/` avant l'archivage, par
`build.bat` comme par la CI. Le build échoue si elle est absente.

Toutes les dépendances sont embarquées ; aucun Python requis chez l'utilisateur.

---

## 🤝 Contributeurs

- **Ghislain DOUCY** — Créateur principal
- **Claude AI** — Intégration IA multi-fournisseurs, bench thermique, refactoring qualité

---

## 📄 Licence

Ghisdiag est distribué sous licence **[PolyForm Noncommercial 1.0.0](./LICENSE)**.

- ✅ **Usage libre et gratuit** pour les particuliers, l'éducation, la recherche, les associations et le secteur public
- ✅ Tu peux l'utiliser, le modifier et le partager pour tout usage **non commercial**
- ❌ **Usage commercial et revente interdits** sans autorisation écrite de l'auteur

Pour un usage commercial (ex. utilisation en atelier de réparation, intégration dans une offre payante), une licence dédiée est nécessaire : écris à **[ghisdiag@laposte.net](mailto:ghisdiag@laposte.net)**.

### Composants tiers

Ghisdiag redistribue des composants tiers (mesure des températures, données SMART des disques) sous leurs licences respectives (MIT, Apache-2.0, MPL-2.0, GPL-2.0). Le détail des auteurs, licences et sources figure dans **[THIRD-PARTY-NOTICES.md](./THIRD-PARTY-NOTICES.md)** ; les textes de licence sont dans [`licenses/`](./licenses/).

---

## 📚 Documentation

| Doc | Contenu |
|-----|---------|
| [RELEASE_NOTES_v1.6.5.md](./RELEASE_NOTES_v1.6.5.md) | Notes détaillées de la dernière release |
| [THIRD-PARTY-NOTICES.md](./THIRD-PARTY-NOTICES.md) | Composants tiers, licences et sources |
| [MISTRAL_SETUP.md](./MISTRAL_SETUP.md) | Configuration des clés API IA (setup, tarif, dépannage) |
| [CHANGELOG.md](./CHANGELOG.md) | Historique complet du projet |

---

## ❓ FAQ

**Q: L'exe est sûr?**  
A: Oui. Télécharge depuis les [releases GitHub officielles](https://github.com/ghislaindoucy/ghisdiag/releases). Code source ouvert et consultable sur GitHub.

**Q: Ça fonctionne sur Linux/Mac?**  
A: Non, Windows uniquement. C'est spécifique à Windows (WMI, PowerShell, services Windows).

**Q: J'ai besoin de Internet?**  
A: Non, sauf si tu veux l'analyse IA Mistral. Le diagnostic seul est 100% offline.

**Q: Où va l'exe en écrivant les rapports?**  
A: `%USERPROFILE%\Documents\Ghisdiag_Reports` (modifiable dans l'interface).

**Q: Ça mange beaucoup?**  
A: L'exe : ~34 MB. Rapports : ~1-2 MB par diagnostic. RAM pendant exécution : <200 MB.

---

## 📞 Support

- 🐛 **Bug trouvé?** → [Ouvre une issue GitHub](https://github.com/ghislaindoucy/ghisdiag/issues)
- 💡 **Suggestion?** → [Ouvre une discussion](https://github.com/ghislaindoucy/ghisdiag/discussions)
- 📖 **Question?** → Lis les docs d'abord 😉

---

## ☕ Soutenir le projet

Vous avez aimé mon travail ? Si le logiciel vous est utile et que vous avez envie de m'offrir un café, vous pouvez me récompenser via PayPal :

👉 **[paypal.me/spiriteom](https://www.paypal.com/paypalme/spiriteom)**

Merci beaucoup, ça fait toujours plaisir et ça encourage à continuer ! 🙏

---

<div align="center">

**Fait avec ❤️ pour les PC qui souffrent.**

[⬇️ Télécharge v2.1.0](https://github.com/ghislaindoucy/ghisdiag/releases/tag/v2.1.0) • [Changelog](./CHANGELOG.md) • [Rapport d'erreur](https://github.com/ghislaindoucy/ghisdiag/issues)

</div>
