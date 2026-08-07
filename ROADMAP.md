# Ghisdiag — Résumé & Roadmap

**Version actuelle : 2.1.0** (2026-08-05) — [Release](https://github.com/ghislaindoucy/ghisdiag/releases/tag/v2.1.0)

---

## 📋 L'application aujourd'hui

Ghisdiag est un **outil de diagnostic et de maintenance Windows tout-en-un**, compilé
en un seul exécutable (PyInstaller, ~34 MB), sans aucune dépendance à installer sur la
machine cible. Pensé pour le technicien SAV : on branche, on lance, on repart avec un
rapport.

### Ce qu'il fait (5 onglets)

**⚙️ Setup / MAJ** — premier onglet, celui du premier geste sur une machine
- Heure & veille : mise à l'heure par Internet (NTP) **ou** saisie manuelle
  (atelier sans réseau), fuseau horaire, blocage de la mise en veille
- Comptes locaux (création, renommage, expiration de mot de passe)
- Mises à jour logicielles via winget
- PC Neuf : installation silencieuse des essentiels + icônes du bureau
- Récupération : partition de récupération, BitLocker

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

### v2.1.0 — ⚙️ Setup en tête, heure et veille ✅ *livré*

- **« Setup / MAJ » passe en 1er onglet** (il était 5e) : c'est l'onglet du
  premier geste sur une machine fraîchement réinstallée, et l'application
  s'ouvre désormais dessus.
- **Nouveau sous-onglet « Heure & veille »** (`collectors/time_manager.ps1`) :
  horloge vivante, fuseau actif, source de temps et état du service W32Time.
  Mise à l'heure par **synchronisation NTP** (`w32tm`, serveur au choix) **ou**
  par **saisie manuelle** — les deux chemins sont indépendants parce que la
  machine d'atelier n'a souvent pas encore de réseau ; l'échec de la synchro
  renvoie vers la saisie manuelle. Choix du fuseau dans la liste Windows
  complète. Machine du domaine détectée : pas de réécriture de la liste de
  pairs NTP, seulement une demande de rafraîchissement.
- **Blocage de la mise en veille** (`power_keepalive.py`,
  `SetThreadExecutionState` porté par un thread dédié) avec option écran
  allumé. **Activé automatiquement par le bench thermique** : un test dure
  jusqu'à ~17 min sans interaction, et rien n'empêchait jusqu'ici la machine de
  s'endormir en pleine charge — ce qui rendait la session inexploitable.
  Demandes distinctes pour l'interrupteur et le bench, état réel confirmé par
  Windows (un refus n'est pas affiché comme un succès).
- **Notice PDF livrée dans l'archive**, à côté de `Ghisdiag.exe` (préparé en
  2.0.3, effectif à ce build).

**🩹 Re-build du 07/08/2026** — même numéro de version, archive republiée
(nouvelle empreinte SHA-256) :

- **Éjection de la clé API** (`prefs.clear_api_keys`) : la clé est retirée de
  `prefs.json`, pas remplacée par une chaîne vide chiffrée — `save_prefs`
  n'écrit plus jamais une clé vide. Éjection groupée si plusieurs fournisseurs
  sont renseignés. Nécessaire pour laisser Ghisdiag installé chez un client.
- **Renommage de compte** (`collectors/user_manager.ps1`) : `Rename-LocalUser`
  ne change que le nom SAM ; le nom **affiché** par Windows est `FullName`, qui
  n'était jamais mis à jour — d'où un renommage invisible à l'écran de connexion
  même après redémarrage. `Set-LocalUser -FullName` a été ajouté ; son échec
  reste un succès assorti d'un avertissement, le compte étant bien renommé.
- **`save_prefs` partiel** : le choix d'un dossier de sortie réécrivait le
  fichier de préférences avec cette seule clé, effaçant fournisseur IA et clés
  API. Toute écriture relit désormais `load_prefs()` d'abord.

### v2.0.3 — 🌡️ Le bench ne conclut plus sur un test incomplet ✅ *livré*

Clôture du chantier « fiabilité du bench thermique » : les 10 défauts relevés en
atelier sont traités.

- **Charge écourtée = throttling indéterminé** (défaut 10). Un `False` n'est plus
  rendu comme une absence quand la charge a été coupée avant le régime établi ;
  un `True` reste un `True`, une détection sur fenêtre courte reste une détection.
  La note dit la vraie cause : fréquence illisible **ou** test trop court.
  Requalification à la lecture — les sessions archivées se corrigent seules.
- **Repos de référence contrôlé** (défaut 4). `idle_load_pct` / `idle_polluted` :
  au-delà de 10 % de charge CPU pendant la phase de repos, la référence est
  signalée. Les valeurs sont conservées (le ΔT reste un minorant), mais une
  comparaison dont **une seule** session est concernée ne chiffre plus de gain —
  c'est l'asymétrie qui fabriquait un faux gain. Nouvelle colonne « Repos de
  référence » dans le rapport.
- **Figeage du flux de capteurs survivable** (défaut 6). Le backend est relancé
  au lieu d'être abandonné ; une coupure pendant la charge arrête la charge par
  sécurité mais laisse mesurer le refroidissement. Les trous sont enregistrés
  (`stream_gaps`), et le plus long silence est mesuré même sous le seuil du chien
  de garde (`sensor_max_gap_sec`) — la trace qui manquait pour comprendre le cas
  du 27/07.

### v2.0.2 — 🚨 Mark of the Web ✅ *livré*

- **Aucun capteur ne remontait après un téléchargement normal.** L'Explorateur
  Windows recopie la marque « vient d'Internet » sur chaque fichier extrait d'une
  archive téléchargée ; .NET refuse alors `LoadFrom` (HRESULT 0x80131515) et plus
  aucune bibliothèque LibreHardwareMonitor ne se charge.
- Introduit par le passage en `onedir` (v2.0.0) : en `onefile`, PyInstaller
  extrayait les DLL lui-même dans `%TEMP%`, sans marque. Invisible en
  développement et sur clé USB, où les fichiers sont **copiés**.
- Correctif : `Unblock-File` sur le dossier `tools` avant chargement, dans les
  trois scripts qui chargent des assemblies.
- Trouvé grâce à la remontée des causes d'erreur livrée en 2.0.1 — sans elle, le
  journal ne disait que « les capteurs ne répondent pas ».

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

---

## 🔜 Chantiers préparés (pas encore engagés)

*Conception arrêtée le 07/08/2026. Rien n'est codé : ces deux sections fixent les
décisions d'architecture et les garde-fous avant la première ligne.*

### v2.2.0 — 📎 Pièces jointes au diagnostic IA 🔜 *préparation*

**Le besoin** : quand un bench thermique vient d'être joué sur la machine, l'audit IA
ne le voit pas. Il raisonne sur un instantané de collecteurs alors qu'on dispose d'une
mesure sous charge — la donnée la plus parlante pour juger un refroidissement.

Ce chantier livre le **mécanisme générique de pièce jointe** que réutilisera ensuite le
module disque ; le bench thermique en est le premier client.

- **Bloc séparé, placé AVANT le dump JSON** dans le prompt, avec son propre budget.
  Le prompt est plafonné à 120 000 caractères et le JSON compact frôle déjà les 109 k
  sur machine chargée (`ai_analyzer._build_user_prompt`) ; la troncature coupe la
  **fin** de la chaîne. Une pièce jointe glissée dans `data` serait donc la première
  sacrifiée, en silence. Seul le diag se tronque.
- **Digest, jamais la session brute** : `metrics` + verdict, plus une courbe
  ré-échantillonnée (~20 points) pour donner la forme de la rampe et du plateau. Les
  séries d'échantillons (`clock_samples`, températures) restent hors prompt.
- **Le tri-état doit survivre au transfert.** `thermal_bench` distingue soigneusement
  « pas de throttling » de « non mesuré » (charge écourtée, session avortée, arrêt
  d'urgence — cf. v2.0.3). Aplatir ça en booléen ferait conclure « refroidissement
  sain » à partir d'un test qui n'a jamais atteint le régime établi : exactement le
  faux négatif que ce code évite. Le digest porte explicitement
  *non mesuré* / *écourté* / *avorté*, et le prompt interdit d'en tirer un verdict.
- **Prompt système à compléter** : il n'a aujourd'hui aucun seuil thermique dans ses
  « SEUILS DE RÉFÉRENCE » et aucun domaine thermique dans le plan d'audit — la donnée
  serait ignorée ou interprétée au jugé. Ajouter les seuils (Tjmax, plancher de
  throttling, écart CPU/GPU), une ligne de domaine en section 3 et un renvoi en
  section 10 (matériel / durée de vie), où le bench est l'argument chiffré d'un
  nettoyage ou d'un repâtage.
- **Comparaison avant/après** : si `thermal_compare` a produit un avant/après, c'est le
  **delta** qu'on joint, pas les deux sessions — l'information est là.

**Tranché (07/08/2026)** :

- **Fenêtre de fraîcheur : la session du jour, et rien d'autre.** C'est la réalité
  atelier — on benche et on diagnostique dans la même passe. Une fenêtre plus large
  ferait tôt ou tard joindre un bench d'avant intervention et conclure l'IA sur un état
  périmé. Aucun bench du jour → aucune pièce jointe, et le prompt reste strictement
  celui d'aujourd'hui (zéro régression).
- **Une session par cible : le bench CPU **et** le bench GPU sont joints** quand les
  deux existent. Ce sont deux mesures indépendantes, et l'écart entre les deux est
  lui-même un signal de diagnostic. Le coût en prompt est négligeable une fois le
  digest réduit.

---

### GhisdiagDisk — 💽 Test de santé disque autonome & bootable 🔜 *préparation — gros chantier*

**Le besoin** : SMART dit ce que le firmware veut bien avouer ; seul un test de surface
dit ce que le disque fait vraiment. Et les disques qu'on suspecte le plus sont ceux des
machines qui **ne démarrent plus** — donc inaccessibles à un module intégré à Ghisdiag.

**Décision d'architecture : outil autonome, bootable, à part.** Même dépôt, code
partagé, mais second exécutable et second `.spec`. Ce qu'on y gagne :

- on teste enfin la population qui en a besoin (machines qui ne bootent pas) ;
- **zéro interférence** : hors OS installé, pas d'indexation, pas de pagefile, pas
  d'antivirus en fond — les mesures de latence deviennent propres, et le problème des
  faux positifs sur le disque système disparaît ;
- **la clé USB devient l'archive** : les rapports s'accumulent, indexés par n° de série
  de disque, et le delta SMART entre deux passages atelier tombe gratuitement.

#### La contrainte qui commande tout : WinPE

Live CD = **WinPE** (pas Linux, sinon on réécrit tout). WinPE n'a **ni .NET ni
PowerShell** par défaut. Sont donc exclus d'office : toute la chaîne capteurs
(`collectors/sensors.py` pilote un PS1 qui charge `LibreHardwareMonitorLib.dll` en
.NET), tous les collecteurs `.ps1`, toute dépendance WMI ou lettre de lecteur (en PE
les volumes ne sont pas forcément montés).

Périmètre autorisé, et suffisant : **Python + `ctypes` sur `\\.\PhysicalDriveN` +
`smartctl.exe`**. C'est aussi le périmètre qui évite d'ajouter un binaire natif de
lecture disque brute — précisément ce que les heuristiques antivirus signalent. Les
deux contraintes convergent. `collectors/disk_temp.py` est déjà sur smartctl (pas LHM)
et reste réutilisable tel quel.

#### Phase 0 — la sonde de validation est prête ✅

Rien ne doit être développé avant d'avoir mesuré ces réponses sur une vraie machine
bootée. La sonde `atelier_winpe_probe.py` (+ `WinPEProbe.spec`) existe et répond aux
**six questions bloquantes** :

1. **tkinter s'affiche-t-il en WinPE ?** — si non, le module se fera en mode console.
   Ce n'est pas rédhibitoire, mais ça change toute l'UI.
2. **smartctl répond-il en PE**, et sur quels contrôleurs ?
3. **L'accès `\\.\PhysicalDriveN` fonctionne-t-il ?**
4. **La lecture non bufferisée alignée secteur passe-t-elle ?** — le module en dépend :
   sans elle on mesure le cache Windows, pas le disque.
5. **Le n° de série du disque est-il lisible ?** — seule clé d'identité valable, le
   hostname vaut `MINWINPC` en PE. Deux sources croisées : IOCTL et smartctl.
6. **Le rapport peut-il être écrit à côté de l'exe ?** — en PE, `X:` est un disque RAM,
   ce qui y est écrit disparaît à l'extinction.

La sonde est **strictement en lecture seule** sur les disques et écrit son rapport
**au fil de l'eau** : si tkinter fait tomber le process — le risque même qu'on mesure —
tout ce qui précède reste sur la clé. Elle mesure aussi 64 Mio séquentiels avec le
**temps maximum par bloc**, qui est l'indicateur clé du futur balayage (un bloc très
lent = secteur en train de mourir), pour prouver que la mécanique de mesure tient en PE.

**Procédure :**

```
pyinstaller --clean --noconfirm WinPEProbe.spec
```

puis copier tout `dist\WinPEProbe\` à la racine de la clé USB bootable, booter la
machine d'atelier dessus, lancer `WinPEProbe.exe`, et récupérer le JSON
`winpe_probe_<machine>_<horodatage>.json` écrit à côté. Le verdict des six points
s'affiche aussi à l'écran, sans avoir à ouvrir le JSON.

Cible de validation : **Hiren's BootCD PE** (Win10 PE déjà garni, répandu en atelier,
aucun build ADK nécessaire) — si ça tourne là, l'outil est livrable.

*Essai sur un Windows normal* : `test_winpe_probe_atelier.bat`, **en tant
qu'administrateur** (sans élévation, l'énumération des disques remonte vide).

**État au 07/08/2026** : sonde exécutée de bout en bout sur le poste de dev
(Windows 11, non élevé). tkinter, smartctl et l'écriture du rapport sont validés ;
les quatre chemins disque (énumération, lecture brute, NO_BUFFERING, n° de série)
**restent à valider en élevé, puis en WinPE**.

#### Les trois niveaux de test — séparation **structurelle**, pas une case à cocher

Une case « mode destructif » est la mécanique même de l'accident : elle reste cochée de
la machine précédente, ou on la coche sur le mauvais disque.

| | Ce que ça écrit | Risque client | Cible |
|---|---|---|---|
| **T1 — Lecture seule** | rien, jamais | nul | tout disque, y compris mourant avec données |
| **T2 — Écriture sur espace libre** | un fichier temporaire créé puis supprimé | faible | disque monté, sain, avec de la place |
| **T3 — Écriture brute pleine surface** | tout le périphérique | destruction totale | disque à effacer, disque neuf, disque condamné |

**Pourquoi T3 mérite d'exister** : c'est le seul moyen de détecter la **corruption
silencieuse** — un disque qui accepte une écriture, la confirme, et relit autre chose.
SMART ne le voit pas, la lecture seule ne peut pas le voir. Usages atelier :
valider un disque neuf avant montage (burn-in), certifier un effacement avant revente.

**T2 traverse la couche NTFS** : il mesure autant le système de fichiers que le disque,
à ne pas vendre pour plus que ça. Et il remplit le disque → à interdire sur un volume
système presque plein.

#### Garde-fous, par ordre d'efficacité réelle

1. **Fichier-marqueur sur la clé** — T3 n'est proposé que si
   `ECRITURE_DESTRUCTIVE_AUTORISEE.txt` est présent à côté de l'exe. La clé d'atelier
   courante ne le contient pas : elle est **physiquement incapable** de détruire quoi
   que ce soit, quel que soit le nombre de clics. Une seconde clé étiquetée sert aux
   effacements. Protection la plus forte de la liste — elle ne dépend pas de la
   vigilance du technicien à 23 h.
2. **Confirmation par saisie du n° de série**, pas par bouton. Protège surtout du
   **mauvais disque**, qui est l'accident le plus fréquent : en PE sans lettres de
   lecteur, `PhysicalDrive0` et `PhysicalDrive1` se confondent en une seconde.
3. **Exclusion inconditionnelle du périphérique de boot** — en PE on a booté sur la clé
   du technicien, elle apparaît dans la liste des disques. Jamais sélectionnable.
4. **Inventaire du contenu affiché avant de proposer T3** (partitions, labels, taux
   d'occupation). Refus sur volume chiffré BitLocker ou schéma de partitions illisible :
   dans le doute, on ne détruit pas.
5. **Passe de lecture systématique avant toute écriture**, même en T3 — si le disque
   « vide » contient une partition pleine, ça remonte avant qu'un octet ne soit écrit.
6. **Aucune persistance du choix** : T1 au lancement, toujours. Le bouton T3 n'a pas le
   focus clavier par défaut.

#### ⚠️ Avertissement métier à intégrer à l'outil

**Balayer intégralement un disque mourant peut l'achever.** Sur un disque mécanique en
défaillance, des heures de lecture de surface accélèrent la dégradation et réduisent les
chances de récupération. L'ordre correct est **imager d'abord, tester ensuite**.

Traduction dans l'outil : mode express par défaut, et écran d'avertissement au
lancement d'un scan long quand SMART est déjà dégradé. Versant commercial : le rapport
est d'autant plus solide qu'il peut dire *« test non poussé volontairement, données
préservées, imagerie recommandée »*.

#### Ce que contient un test

Par ordre de rapport valeur / effort :

1. **Balayage de lecture** (le cœur) — lecture brute en relevant les secteurs illisibles
   **et les temps de lecture aberrants** : un bloc qui met 800 ms à sortir est un secteur
   en train de mourir que SMART ne compte pas encore.
2. **Profil de latence en lecture aléatoire** (p50/p99) — contrôleur SSD dégradé, SMR
   qui rame, NAND fatiguée.
3. **Débit séquentiel comparé à la classe** du périphérique — un SATA SSD à 40 Mo/s,
   c'est un disque mourant ou un lien retombé en mode dégradé.
4. **Projection d'usure** — NVMe `percentage_used` + écritures hôte rapportées à l'âge
   → durée de vie restante en années. Quasi gratuit (donnée déjà collectée) et c'est ce
   qui parle le plus au client.
5. **Delta SMART historique** — secteurs réalloués qui *augmentent* entre deux passages
   atelier : signal bien plus fort qu'une valeur absolue.
6. **Auto-test SMART** (`smartctl -t short`) + journal d'auto-tests — 2 min, déjà outillé.
7. **Écriture soutenue** (falaise de cache SLC) et **throttling thermique NVMe** — là on
   réutilise l'infrastructure du bench thermique. *(T2/T3)*

#### Contraintes d'exécution

- **Durée** : balayage complet d'un HDD 4 To à 120 Mo/s ≈ 9 h. D'où trois modes —
  **express** (début/fin + N zones réparties, ~2 min), **standard** (~15 min),
  **complet** (opt-in explicite, on laisse tourner la nuit).
- **Journalisation incrémentale obligatoire** : un scan de 9 h interrompu (gel, disque
  qui lâche, coupure) doit laisser un rapport partiel exploitable. Écriture au fil de
  l'eau, reprise sur checkpoint.
- **Écriture des rapports à côté de l'exe** (donc sur la clé USB), repli sur `Documents`
  sous Windows normal. En PE, `X:` est un disque RAM : tout ce qui y est écrit disparaît
  à l'extinction.
- **Identité du rapport sans le nom de machine** : en WinPE le hostname est `MINWINPC`,
  inutilisable. Clé d'identification = **n° de série du disque** (+ série carte mère si
  disponible). C'est aussi ce qui permettra à Ghisdiag de retrouver le rapport
  correspondant et de le joindre au diag IA (mécanisme v2.2.0).
- **Exclusions** : USB, RAID, disques virtuels — comme le bench thermique le fait déjà.

#### Le rapport client

Livrable distinct du JSON, et c'est là qu'est la valeur commerciale : il justifie un
devis de remplacement. **HTML auto-porté** (s'ouvre partout, aucune dépendance) ; pas de
PDF généré sur place — Chrome n'existe pas en PE, la conversion se fera au besoin sur le
poste du technicien, comme pour la notice.

Contenu : identité machine + disque + n° de série, date, version de l'outil, verdict en
trois états, et les chiffres qui l'étayent. Et surtout **le mode de test en en-tête, en
clair** :

- T1/T2 → « **Test non destructif** — aucune écriture sur les données existantes,
  contenu du disque préservé. »
- T3 → « **Test destructif** — l'intégralité du contenu a été effacée », avec un champ
  **autorisation** rempli avant lancement (nom du client / référence du devis) et repris
  dans le rapport.

Un rapport horodaté qui dit noir sur blanc « aucune écriture » est ce qui clôt une
discussion si un client revient en disant qu'il a perdu des fichiers.

#### Coût à assumer

**Deuxième exe = deuxième front antivirus.** Un binaire autonome qui ouvre le disque en
accès brut coche des cases heuristiques que Ghisdiag ne coche pas. Il lui faudra sa
propre attestation SLSA et son propre passage VirusTotal, à chaque release. En
contrepartie son périmètre est bien plus maigre (ni `collectors/*.ps1`, ni DLL .NET, ni
PawnIO — juste `smartctl.exe`), donc un binaire plus léger et moins suspect que le
principal.

#### Phasage

| Phase | Contenu | Poids |
|---|---|---|
| 0 | Spike WinPE (`atelier_winpe_probe.py`) — sonde écrite, reste à jouer en PE | petit, **bloquant** |
| 1 | Moteur T1 (balayage lecture + débit + latence), modes express/standard, session checkpointée | gros |
| 2 | Rapport client HTML + verdict + identité par n° de série | moyen |
| 3 | Auto-test SMART + delta historique + remontée vers le diag IA de Ghisdiag | moyen |
| 4 | T2 (écriture espace libre) : falaise SLC, throttling NVMe | moyen |
| 5 | T3 (écriture brute) + fichier-marqueur + saisie du n° de série + champ autorisation | moyen |

**Recommandation v1 : T1 seul.** Il couvre déjà le cas d'usage principal — juger un
disque suspect sans toucher aux données — et c'est le seul niveau utilisable sur les
machines qui inquiètent. Mais **l'architecture à trois niveaux se pose dès maintenant**
(le niveau est un attribut de la session, il apparaît dans le rapport, le
fichier-marqueur est déjà lu), pour que T3 s'ajoute plus tard sans rouvrir le chemin
d'écriture d'un outil déjà en production. Greffer un mode destructif après coup sur une
base qui n'a jamais écrit, c'est là qu'on se blesse.

---

### Plus tard / opportuniste

- **Signature de code** de l'exe (réduction des faux positifs antivirus — process déjà
  documenté dans build.bat, il manque le certificat)
- Export PDF du rapport
- Mode « rapport client » simplifié (vulgarisé, sans jargon)

---

*Document vivant — mis à jour à chaque release.*
