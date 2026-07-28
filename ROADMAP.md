# Ghisdiag — Résumé & Roadmap

**Version actuelle : 2.0.1** (2026-07-28) — [Release](https://github.com/ghislaindoucy/ghisdiag/releases/tag/v2.0.1)

---

## 📋 L'application aujourd'hui

Ghisdiag est un **outil de diagnostic et de maintenance Windows tout-en-un**, compilé
en un seul exécutable (PyInstaller, ~34 MB), sans aucune dépendance à installer sur la
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
  processus Python enfant réextrairait les ~34 Mo du bundle
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

### v1.8.1 — 🖥️ Interface défilable sur petits écrans ✅ *livré*

- **Tous les onglets défilables** : Analyse et Bench thermique rejoignent
  Dépannage / WiFi / Setup via un helper `_scrollable()` unique (les 6 zones
  jusque-là dupliquées sont factorisées). Barre affichée seulement si la fenêtre
  est trop courte ; sur grand écran, journal et graphe s'étirent comme avant.
- **En-tête compact** sous 800 px de hauteur logique (portables 14", mise à
  l'échelle Windows où l'app non DPI-aware ne voit que ~1280×720) : sous-titre
  masqué, logo réduit, liens sur une ligne → ~100 px rendus au contenu.
- **Fenêtre restaurée bornée à l'écran** (ne dépasse plus sous la barre des
  tâches).
- **Correctif molette** : chaque panneau posait un `bind_all` global, la dernière
  zone construite captait la molette de toute l'app → routeur unique.
- Validé en atelier (HP Pavilion 14-ce0009nf, 1080p en mise à l'échelle).

### v2.0.1 — 🌡️ Fiabilité du bench thermique ✅ *livré*

- **Ne plus affirmer ce qui n'a pas été mesuré.** `throttling` et `power_limited`
  passent en tri-état (oui / non / indéterminé) ; sans fréquence relevée, l'outil
  ne conclut plus. Les sessions au schéma v1 restent relisibles.
- **Mapping capteur des Intel hybrides** (`P-Core #N` / `E-Core #N`) : aucune
  fréquence n'était collectée depuis Alder Lake, ce qui désactivait en silence
  toute la détection de throttling.
- **Charge écourtée** : plateau et ΔT invalidés plutôt que calculés sur une rampe.
- **Limite de puissance PL1** détectée en comparant la fenêtre turbo au régime
  établi, elle-même ancrée sur la charge réelle (un générateur peut mettre
  plusieurs dizaines de secondes à démarrer).
- **Conditions de mesure** contrôlées par la comparaison avant/après ; verdict
  « non concluant » quand les deux sessions ne se comparent pas.
- **Diagnostic** : cause des refus capteurs remontée, contexte d'exécution
  journalisé au démarrage, journal de production isolé des tests.
- Validé sur quatre machines d'atelier et confronté à HWiNFO.

### v2.0.0 — 📦 Distribution en dossier portable ✅ *livré*

- **Passage de PyInstaller `onefile` à `onedir`.** Sortie du build : le dossier
  `dist\Ghisdiag\` (1126 fichiers, ~78 Mo) et l'archive `dist\Ghisdiag.zip`
  (~34 Mo, soit la taille de l'ancien exe) publiée en release. Motivation
  première : l'usage sur clé USB en atelier, où `onefile` décompressait 34 Mo
  dans le `%TEMP%` du client à chaque lancement.
- **`Ghisdiag.spec` et `Ghisdiag.manifest` versionnés** (exceptions dans
  `.gitignore`) et consommés tels quels par `build.bat` **et** par la CI :
  une seule source de vérité pour les options de compilation. `build.bat` ne
  régénère plus ces fichiers, et produit le ZIP en fin de course.
- **Workflow GitHub Actions** (`.github/workflows/build-release.yml`) : compile
  sur tag `v*` et génère une **attestation de provenance SLSA** sur l'archive et
  sur l'exe. C'est le principal levier anti-faux-positif disponible sans
  certificat de signature payant.
- **Antivirus** : `upx=False`, sauvegarde WiFi sans `key=clear` par défaut,
  et nouveau `docs/transparence-systeme.md` recensant toutes les opérations
  privilégiées — document à joindre aux signalements de faux positifs.
- **Correctif UAC** : `EXE(manifest=…)` ne suffisait pas ; PyInstaller réécrit le
  `<requestedExecutionLevel>` depuis son paramètre `uac_admin` et forçait
  `asInvoker`. Le `requireAdministrator` du manifeste était donc inopérant depuis
  toujours, et l'app compensait via `request_elevation()` — un double lancement
  du process à chaque démarrage. Corrigé par `uac_admin=True`.
- **Correctifs moniteur** : températures disque publiées dès le premier tick
  (au lieu du 5ᵉ, soit 10 s) et découplées du repli WMI de la température CPU
  (1 à 6 s, déclenché à chaque cycle sur une machine sans PawnIO).
- **`GHISDIAG_DEBUG=1`** : journal en `DEBUG` avec bloc de contexte au démarrage
  (version, gelé/sources, ressources, élévation, imports optionnels ratés et leur
  cause). Les journaux HTTP restent en `INFO` pour ne jamais tracer de clé API.

### v1.8.2 — 🤖 Question libre à l'IA ✅ *livré*

- **Champ question optionnel** (500 car., compteur en direct) dans le panneau
  Analyse IA, affiché seulement quand une clé API est active
  (`_toggle_ai_question_row`). La question est propagée du thread d'analyse
  jusqu'au prompt et au rapport.
- Prompt : `_build_question_block()` injecté en tête du prompt utilisateur
  (`ai_analyzer.py`). Sans question → prompt strictement identique (zéro
  régression). Garde-fou : réponse **seulement si dans le sujet** (poste /
  panne / réparation Windows), **refus poli** sinon, puis audit complet dans
  tous les cas. Réponse placée en section « Réponse à ta question » en tête.
- **Sécurité prompt** : question neutralisée (backticks et sauts de ligne
  retirés, tronquée à 500) — traitée comme donnée, pas comme instruction
  (anti-injection).
- Rapport : la question posée est rappelée dans l'encart méta du rapport IA
  (`ai_report.py`).
- Validé en atelier (question dans le sujet + question hors-sujet pour vérifier
  le refus poli).
- 🩹 **Correctif (re-build du 24/07, version inchangée)** — bench thermique :
  la détection GPU tournait dans un thread lancé pendant la construction de
  l'UI et publiait son résultat via `after()`. Appelé depuis un autre thread
  avant `mainloop()`, `after()` lève `RuntimeError` après ~1 s : le thread
  mourait en silence (exe sans console) et `_bench_gpu_detect` restait `None` à
  vie → cible GPU refusée en boucle. Visible surtout sur machine NVIDIA
  (détection NVML ~50 ms, donc terminée trop tôt ; le repli LHM, 1-3 s, passait
  au travers). Détection déplacée après `mainloop()`, réessais côté thread, et
  relance à chaque bascule sur la cible GPU. Couvert par
  `tests/test_bench_gpu_detect.py`.

### Plus tard / opportuniste

- **Signature de code** de l'exe (réduction des faux positifs antivirus — process déjà
  documenté dans build.bat, il manque le certificat)
- Benchmark disque simple (débit séquentiel/aléatoire avant/après remplacement)
- Export PDF du rapport
- Mode « rapport client » simplifié (vulgarisé, sans jargon)

---

*Document vivant — mis à jour à chaque release.*
