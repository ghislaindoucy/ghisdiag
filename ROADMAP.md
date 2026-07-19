# Ghisdiag — Résumé & Roadmap

**Version actuelle : 1.8.0** (2026-07-19) — [Release](https://github.com/ghislaindoucy/ghisdiag/releases/tag/v1.8.0)

---

## 📋 L'application aujourd'hui

Ghisdiag est un **outil de diagnostic et de maintenance Windows tout-en-un**, compilé
en un seul exécutable (PyInstaller, ~19 MB), sans aucune dépendance à installer sur la
machine cible. Pensé pour le technicien SAV : on branche, on lance, on repart avec un
rapport.

### Ce qu'il fait (4 onglets)

**🔍 Analyse** — le cœur du produit
- 8 collecteurs PowerShell exécutés en parallèle (~20 s) : système, performances,
  démarrage/services, événements, réseau, sécurité, logiciels/drivers, santé disques
- **Journaux de fiabilité niveau 3** : BSOD avec code BugCheck, erreurs matérielles
  WHEA, erreurs disque, corruption NTFS, services en échec
- **SMART complet** via smartctl embarqué (NVMe : usure, spare, erreurs ; SATA : attributs)
- Rapport **HTML interactif** (thème Catppuccin) + **JSON** exploitable par une IA
- **Audit IA Mistral** optionnel : 10 sections, corrélations entre données, cause
  racine, niveau de confiance — et zéro problème inventé (garde-fous anti-faux-positifs)
- Moniteur temps réel CPU / RAM / disque / températures

**🔧 Dépannage**
- Impression : spooler, files d'attente, annulation, page de test
- Réseau : état des cartes, réinitialisation
- Réparation système : SFC + DISM en streaming avec suivi live

**📶 WiFi**
- Profils enregistrés : consultation (avec mot de passe), suppression, sauvegarde/restauration
- Scan des réseaux et connexion

**⚙️ Setup / MAJ**
- Comptes locaux (création, renommage, expiration de mot de passe)
- Mises à jour logicielles via winget
- PC Neuf : installation silencieuse des essentiels + icônes du bureau
- Récupération : partition de récupération, BitLocker

### Architecture (pour mémoire)

```
main.py               UI tkinter (thème Catppuccin Mocha)
orchestrator.py       exécution parallèle des collecteurs PS1
collectors/*.ps1      collecte (pattern Safe-Get partagé)
report/generator.py   rapport HTML/JSON + règles d'alertes déclaratives
mistral_analyzer.py   audit IA (prompt rigueur + profondeur)
prefs.py / security.py  préférences persistées, UAC, garde-fous
```

---

## 🗺️ Roadmap

### v1.5.0 — 🌡️ Bench thermique avant/après maintenance ✅ *livré*

**Le besoin** : objectiver le gain d'un nettoyage ou d'un changement de pâte thermique.
Courbes de température **avant** intervention, courbes **après**, et chiffrage du gain —
un argument concret à montrer au client.

#### Phase 0 — Source de températures fiable *(prérequis)*

La collecte actuelle (WMI `MSAcpi_ThermalZoneTemperature`, souvent vide sur desktop ;
namespace OpenHardwareMonitor, exige OHM lancé) est trop fragile pour un bench.

- Embarquer **LibreHardwareMonitorLib.dll** (MPL 2.0, redistribuable) chargée depuis
  un collecteur PowerShell (`Add-Type -Path`) qui dump tous les capteurs en JSON —
  même pattern que smartctl (`--add-binary`)
- Capteurs cibles : CPU package + cœurs, GPU, disques, **vitesses ventilateurs**
  (précieux pour diagnostiquer un ventirad encrassé) et fréquences CPU
- Fallback : chaîne actuelle si la DLL échoue
- Bénéfice immédiat : le moniteur temps réel affiche enfin des températures partout

#### Phase 1 — Moteur de bench

- **Protocole en 3 phases** : repos (~2 min, baseline) → charge (5-10 min, stress CPU
  configurable 50/100 %) → refroidissement (~5 min)
- Génération de charge par **workers PowerShell** (runspaces .NET, un par cœur
  logique, sans GIL) plutôt que multiprocessing Python : en `--onefile` chaque
  processus Python enfant réextrairait les ~20 Mo du bundle
- Échantillonnage toutes les 2-5 s : températures + charge + fréquence CPU
- **Détection de throttling** : fréquence qui s'effondre quand la température plafonne
- **Arrêt d'urgence** : automatique si T > 95 °C, ou bouton Stop
- Métriques : T idle, T max, T plateau en charge, ΔT, temps de retour au calme
- Session sauvegardée en JSON horodaté, étiquetée **Avant / Après / Libre**
  (`Documents\Ghisdiag_Reports\thermal\`)

#### Phase 2 — UI : nouvel onglet « Bench thermique »

- Courbes **temps réel** sur `tk.Canvas` (multi-séries CPU/GPU/disque, zones colorées
  par phase) — pas de matplotlib : l'exe resterait léger
- Configuration simple : durée, intensité, étiquette avant/après
- Liste des sessions enregistrées de la machine

#### Phase 3 — Comparaison avant/après & gains

- Sélection de 2 sessions → **courbes superposées** + carte des gains :
  ΔT idle, ΔT max, ΔT plateau, Δ temps de refroidissement, throttling éliminé (oui/non)
- **Rapport HTML dédié** avec courbes en SVG auto-généré (offline, imprimable,
  à remettre au client) et verdict clair : *« −12 °C en charge — intervention efficace »*
- Garde-fou honnêteté : comparer uniquement des sessions au protocole identique,
  avertir que la température ambiante n'est pas contrôlée

---

### v1.6.0 — 🤖 Analyse IA multi-fournisseurs ✅ *livré*

- Choix du fournisseur d'analyse IA via une fenêtre de configuration dédiée :
  **Anthropic** (Claude), **Mistral**, **OpenAI** (GPT), **Grok** (xAI), **Google** (Gemini)
  — clé API par fournisseur (chiffrée), bouton de test
- Prompt d'audit expert mutualisé entre fournisseurs ; moteur léger en `requests`
  (3 familles d'API : OpenAI-compatible, Anthropic, Gemini), sans SDK
- Migration automatique de l'ancienne clé Mistral
- Timeout / `reasoning_effort` réglables par fournisseur (OpenAI gpt-5.5 en effort
  « low » + timeout élargi pour éviter les expirations sur audits longs)
- **Bench thermique** : avertissement de responsabilité avant le test, et durée de
  charge personnalisable (presets + saisie libre, comparaison protégée par protocole identique)

---

### v1.7.0 — 🎮 Bench thermique GPU ✅ *livré*

**Le besoin** : le même avant/après objectif que pour le CPU, appliqué à la carte
graphique (dépoussiérage, changement de pâte/pads).

- **Charge GPU vendor-neutral** : compute shader Direct3D 11 piloté en ctypes/COM,
  aucun binaire ajouté (d3d11/dxgi/d3dcompiler = composants Windows), dispatches
  courts calibrés anti-TDR — validé NVIDIA / AMD APU / Intel iGPU, 0 incident
- **Mesures NVML** fiables sous charge (temp, clock, power, raison de bridage du
  pilote) avec session persistante sur le GPU ciblé ; repli LHM pour AMD/Intel
- **UI** : cible CPU/GPU, choix de la carte (iGPU sans capteur écartés), relevés
  temps réel adaptés, liste des sessions filtrée CPU | GPU
- **Sécurité** : arrêt avant le seuil de bridage constructeur (slowdown NVML) ou
  sur bridage thermique confirmé — jamais sur le bit seul (faux positif au repos)
- **Comparaison + rapport HTML GPU** : verdict chiffré, gains (dont hotspot et
  chute de clock), garde-fous protocole identique + même carte
- Suivi de chantier : `GPU_BENCH_PROGRESS.md` (M0→M6, validations atelier)

### v1.8.0 — 🚦 Diagnostic encore plus parlant ✅ *livré*

- **Résumé exécutif « Ce qui ralentit ce PC »** en tête du rapport HTML : top 3
  des freins priorisés par impact perf (moteur de règles `report/exec_summary.py`),
  constat chiffré + action recommandée, findings injectés dans le JSON
  (`executive_summary`) pour l'audit IA et l'historique. Garde-fous honnêteté
  (HDD+SSD conditionnel, USB exclus, mesures instantanées annoncées).
- **Pilotes obsolètes / non signés** : signature/classe/présence par driver,
  tableau des anciens (>5 ans, matériel actif, drivers boîte Windows exclus —
  signataire strict) avec « Où mettre à jour » par classe ; alertes avec
  garde-fou bruit.
- **Analyse du boot par phase** (Event ID 100) : décomposition noyau / pilotes /
  services / profil / bureau + post-boot, piste de diagnostic quand une phase
  domine un démarrage lent.
- **Historique des diagnostics** (`diag_compare.py` + bouton « 📈 Historique… ») :
  deux rapports JSON de la même machine → freins résolus/apparus/persistants,
  12 chiffres clés, usure SMART par disque (apparié par n° de série), verdict
  pondéré amélioration/stable/dégradation. Rétro-compatible JSON pré-1.8.
- Suivi de chantier : `DIAG_V18_PROGRESS.md` (M0→M5).

### Plus tard / opportuniste

- **Signature de code** de l'exe (réduction des faux positifs antivirus — process déjà
  documenté dans build.bat, il manque le certificat)
- Benchmark disque simple (débit séquentiel/aléatoire avant/après remplacement)
- Export PDF du rapport
- Mode « rapport client » simplifié (vulgarisé, sans jargon)

---

*Document vivant — mis à jour à chaque release.*
