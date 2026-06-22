# 🔍 Ghisdiag

> **Diagnostic Windows professionnel + Analyse IA.** Découvrez tous les soucis de votre PC en 2 clics, puis laissez l'IA de votre choix (Claude, Mistral, GPT, Grok ou Gemini) vous générer un plan d'action détaillé.

[![Version](https://img.shields.io/badge/version-1.6.2-blue.svg)](https://github.com/ghislaindoucy/ghisdiag/releases/tag/v1.6.2)
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

### 🤖 Analyse IA multi-fournisseurs

Après ton diagnostic, active l'analyse IA et choisis ton fournisseur — **Anthropic (Claude Opus 4.8)**, **Mistral (Large)**, **OpenAI (GPT-5.5)**, **Grok (xAI 4.3)** ou **Google (Gemini 2.5 Pro)** — pour obtenir :
- ✅ **Audit complet** — ce qui va pas, ce qui peut s'améliorer (avec preuve par problème)
- ✅ **Commandes exactes** — copie-colle direct dans PowerShell/CMD
- ✅ **Plan de réparation** — étapes détaillées pour chaque problème
- ✅ **Optimisations** — gagner en vitesse et stabilité
- ✅ **Priorités claires** — critique → grave → moyen → faible

Clé API par fournisseur (chiffrée AES-128), bouton « Tester la clé », aucun SDK requis.

---

## 🎯 Commencer en 30 secondes

### 1️⃣ Télécharge et lance
```bash
# Récupère Ghisdiag.exe depuis les releases
# Double-clique et c'est parti!
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

### Windows (Exe seul)
1. Télécharge `Ghisdiag.exe` depuis les [releases](https://github.com/ghislaindoucy/ghisdiag/releases)
2. Double-clique
3. Accepte les droits administrateur
4. C'est parti!

**Prérequis :** Windows 10/11, rien d'autre (tout est embarqué dans l'exe)

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
- Clé API par fournisseur (chiffrée), bouton « Tester la clé », migration de l'ancienne clé Mistral
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
- ✅ **Pas de tracking** — tout reste local, aucun envoi de données
- ✅ **Exe signable** — prêt pour signature de code (optionnel)

---

## 🛠️ Build l'exe toi-même

```batch
cd D:\Projets\Ghisdiag
build.bat
```

L'exe généré : `dist/Ghisdiag.exe`
- Toutes les dépendances embarquées
- Aucun Python requis chez l'utilisateur
- ~80-100 MB

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

Pour un usage commercial (ex. intégration dans une offre payante), contacte l'auteur pour une licence dédiée.

---

## 📚 Documentation

| Doc | Contenu |
|-----|---------|
| [RELEASE_NOTES_v1.6.2.md](./RELEASE_NOTES_v1.6.2.md) | Notes détaillées de la dernière release |
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
A: L'exe : ~80 MB. Rapports : ~1-2 MB par diagnostic. RAM pendant exécution : <200 MB.

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

[⬇️ Télécharge v1.6.2](https://github.com/ghislaindoucy/ghisdiag/releases/tag/v1.6.2) • [Changelog](./CHANGELOG.md) • [Rapport d'erreur](https://github.com/ghislaindoucy/ghisdiag/issues)

</div>
