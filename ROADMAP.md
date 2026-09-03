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

## 🔜 Chantiers préparés — point d'entrée

> **Où on en est au 03/09/2026** — branche `claude/diagnostic-consolidation-86e9e8`,
> [PR #33](https://github.com/ghislaindoucy/ghisdiag/pull/33). **Aucun code de production
> n'est touché** : ce qui existe, c'est la conception ci-dessous plus la sonde de terrain
> `atelier_winpe_probe.py`.
>
> | | État |
> |---|---|
> | **v2.2.0** — bench thermique joint au diag IA | conçu, **décisions tranchées**, rien de codé. Ne demande aucun matériel. |
> | **GhisdiagDisk** — outil disque autonome bootable | phase 0 close, **phase 1 ÉCRITE le 03/09** (moteur T1 + CLI console + 49 tests sans matériel, branche `claude/ghisdiaqdisk-balayage-t1-1c9efb`). **Pas encore validée en atelier** : aucune exécution élevée ni en WinPE. |
>
> **Deux points d'attention avant d'engager quoi que ce soit :**
> 1. Les décisions d'architecture ci-dessous ont été prises après discussion et
>    **mesures** — ne pas les re-concevoir de mémoire, les lire.
> 2. Trois d'entre elles ont déjà été **révisées par les mesures** (smartctl comme source
>    de référence, discriminant mécanique/SSD, clé d'identité). Les sections « Campagne »
>    font foi sur les sections antérieures en cas de contradiction.

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
py -m PyInstaller --clean --noconfirm WinPEProbe.spec
```

(`py -m PyInstaller` et non `pyinstaller` : même invocation que `build.bat`, la seule
qui marche quand le paquet est installé sans que ses scripts soient dans le `PATH`.)

puis copier tout `dist\WinPEProbe\` à la racine de la clé USB bootable, booter la
machine d'atelier dessus, lancer `WinPEProbe.exe`, et récupérer le JSON
`winpe_probe_<machine>_<horodatage>.json` écrit à côté. Le verdict des six points
s'affiche aussi à l'écran, sans avoir à ouvrir le JSON.

Cible de validation : **Hiren's BootCD PE** (Win10 PE déjà garni, répandu en atelier,
aucun build ADK nécessaire) — si ça tourne là, l'outil est livrable.

*Essai sur un Windows normal* : `test_winpe_probe_atelier.bat`, **en tant
qu'administrateur** (sans élévation, l'énumération des disques remonte vide).

**État au 08/08/2026** — sonde jouée sur **trois exécutions élevées**, deux machines
(Windows 11 24H2 et Windows 10 22H2), en sources et en exe compilé.

**Tout le socle technique est validé hors WinPE :**

| Point | Résultat |
|---|---|
| tkinter | ✅ fenêtre + `mainloop`, Tcl 8.6.15, sur les deux machines |
| smartctl | ✅ opérationnel, et **sans élévation** |
| Énumération `\\.\PhysicalDriveN` | ✅ 3 disques par machine, taille et secteur lus |
| Lecture brute alignée | ✅ signature MBR/GPT vue |
| `NO_BUFFERING` + tampon aligné | ✅ |
| Débit / latence par bloc | ✅ 1052 et 2778 Mo/s, `bloc_max` 3,79 et 0,62 ms |
| Rapport persistant à côté de l'exe | ✅ |

✅ **Validation WinPE faite le 03/09** — voir « Phase 0 close » plus bas.

**Quatre défauts trouvés par ces exécutions, tous corrigés.** C'est le rendement de la
phase 0 : chacun aurait coûté un aller-retour en atelier.

1. **Le rapport partait dans `_internal\`.** En onedir PyInstaller 6 tout le bundle
   atterrit là et `__file__` pointe dedans : le technicien aurait cherché le JSON à côté
   de l'exe sans jamais le trouver. Le dossier d'écriture vient désormais de
   `sys.executable`, distinct du dossier de lecture des ressources.
2. **La console se refermait avant le verdict** en double-clic — le geste normal en
   WinPE. Pause finale ajoutée, et les exceptions s'affichent avant elle.
3. **La révision de firmware était rendue comme n° de série.** Offsets du
   `STORAGE_DEVICE_DESCRIPTOR` décalés de 4 octets (8/12/16/20 au lieu de 12/16/20/24).
   Défaut **invisible** : le champ était rempli, le verdict annonçait
   `serie_disque_lisible: true`. Deux disques de même modèle et même firmware auraient
   partagé la même « clé d'identité » et leurs rapports se seraient écrasés.
4. **Le croisement des sources manquait.** C'est lui qui aurait attrapé le point 3 tout
   seul : deux sources indépendantes qui ne partagent aucun n° de série alors qu'elles
   répondent toutes les deux, c'est qu'une des deux décode mal. Ajouté, et **par
   disque** — une intersection non vide suffisait à masquer le cas réel.

**Décisions d'architecture que ces mesures imposent :**

- **Le n° de série doit être assaini avant de servir de nom de fichier.** L'IOCTL rend
  pour une clé USB un série contenant des octets de contrôle non imprimables. Utilisé
  tel quel dans le nom du rapport, il produit un fichier illisible ou un échec
  d'écriture.
- **Les règles d'exclusion sont gratuites** : le `BusType` et le drapeau `RemovableMedia`
  du même IOCTL donnent directement `USB` / `SATA` / `NVMe` / `RAID` et l'amovibilité.
  Le dédoublonnage par n° de série sera nécessaire : derrière un contrôleur Intel RST,
  smartctl voit **deux fois le même disque** (`/dev/sdb` et `/dev/csmi1,0`).

---

### 📊 Campagne de collecte (08/08 → 01/09/2026) — 6 machines

Sonde jouée sur 6 postes (Win11 24H2 et Win10 22H2) : **8 disques internes, dont
5 NVMe et 3 SSD SATA**. Elle a invalidé deux décisions prises trop vite et révélé un
angle mort.

**1. ⚠️ Décision RÉVISÉE — smartctl ne peut pas être « la source de référence ».**
Sur **2 machines sur 4**, smartctl restait entièrement muet sur le disque système NVMe
(tous les champs nuls) alors qu'il répondait sur le lecteur DVD de la même machine. Une
source absente une fois sur deux n'est pas une référence.

*Cause identifiée* : `--scan-open` rendait bien le **type** du périphérique (`nvme`,
`ata`, `scsi`) et la sonde **le jetait**, interrogeant ensuite sans `-d <type>`. Corrigé.
À revalider à la prochaine campagne — et si le silence persiste, il faudra un lecteur
SMART NVMe natif (`IOCTL_STORAGE_QUERY_PROPERTY` /
`StorageDeviceProtocolSpecificProperty`), sans quoi le module n'aurait aucune donnée
SMART sur les machines concernées.

**2. La clé d'identité ne peut venir d'une seule source — et un champ rempli n'est pas
un identifiant.** Deux contre-exemples relevés :

- la clé USB rend `\x031`, assaini en **« 1 »** ;
- les NVMe rendent par IOCTL leur EUI-64, souvent presque tout en zéros
  (`0000_0000_0000_0000_0C82_D500_0000_0371`), et certains fabricants partagent le même
  préfixe sur toute une gamme.

Indexer l'archive là-dessus ferait collisionner des rapports de machines différentes.
**Décision** : clé composite avec **niveau de confiance** (forte = smartctl, moyenne =
IOCTL, faible = repli explicite `MODELE-TAILLE-SANS-SERIE`), et un série n'est retenu que
s'il est *discriminant* — au moins 6 caractères, pas un caractère répété, pas
essentiellement des zéros. Prototypé dans la sonde (`synthese_disques`).

**3. `rotation_rate` est TOUJOURS absent en NVMe** (champ ATA) — vérifié sur 5 NVMe. Le
discriminant mécanique/SSD devient une règle en cascade : bus NVMe ou log NVMe présent
→ SSD ; sinon `rotation_rate` 0 → SSD, > 0 → mécanique ; sinon indéterminé.

**4. L'écart de débit entre zones ne conclut rien** — jusqu'à **65,9 %** sur un NVMe
parfaitement sain, contre 3 % sur un SATA du même poste. Et la **zone de début est
systématiquement la plus lente** sur NVMe : mesurer uniquement au début donnerait une
image fausse du disque. Le mode express devra échantillonner plusieurs zones **et**
annoncer la dispersion, jamais conclure dessus.

**5. Exclusion du disque porteur : validée 6/6.** La sonde se reconnaît sur le
périphérique depuis lequel elle tourne, y compris lancée depuis la clé USB. Le garde-fou
n° 3 n'est plus une intention.

**6. 🕳️ L'angle mort : pas un seul disque mécanique dans l'échantillon.** Or c'est la
population que le module vise en priorité — celle qui a des secteurs mourants. Tout le
profil de latence attendu (temps par bloc, écart entre pistes extérieures et intérieures)
reste **non observé**. À couvrir avant d'écrire le moteur de balayage.
*(→ comblé le 02/09, voir ci-dessous.)*

---

### 🎯 Campagne du 02/09 — l'angle mort est comblé, les seuils sont calibrés

16 rapports, **21 disques distincts, dont 12 mécaniques** (80 Go à 1 To, 5400 et
7200 tr/min, Seagate / WD / Toshiba / HGST), plus SSD SATA, NVMe, eMMC, clé USB et un
volume Intel Optane. C'est le jeu de calibration de référence du module.

#### La signature d'un disque mécanique est nette et reproductible

Le débit chute des pistes extérieures vers les intérieures (enregistrement par zones) :

| | ratio fin/début | décroissance monotone |
|---|---|---|
| **11 disques mécaniques** | **0,40 – 0,52** | 11 / 11 |
| SSD SATA et NVMe | 0,98 – 1,84 | 0 / 3 |
| Volume Optane (cache SSD en tête) | 0,08 | oui |
| Clé USB | 0,77 | oui |

**Aucun recouvrement.** C'est la **forme** du profil qui discrimine, jamais l'écart brut
— rappel : un NVMe sain atteint 65 % d'écart. La bande retenue dans le code est élargie
à 0,30–0,65, ce qui exclut toujours l'Optane et l'USB.

Gain immédiat : **3 disques mécaniques anciens** (ST380815AS, WD3200AAJS, WD1600AAJS)
étaient classés « indéterminé » parce qu'ils sont antérieurs à ATA8 et ne publient pas
`rotation_rate`. Le profil les identifie sans ambiguïté. Vérifié en rejouant les règles
sur les 52 mesures archivées : 3 reclassements corrects, **aucun SSD entraîné**.

#### ⚠️ Deux pièges de méthode que seuls des disques mécaniques révèlent

**Le réveil des plateaux ressemble à un secteur mourant.** Premier bloc lu sur un
WD10SPZX en veille : **313 ms**. C'est le démarrage du moteur, pas un défaut — mais
strictement indistinguable si on le compte. Une lecture d'échauffement non mesurée est
désormais faite avant chaque zone ; **le moteur de balayage devra faire de même**, sinon
il annoncera un défaut sur chaque disque endormi.

**16 Mio par zone peuvent tenir dans le cache du disque.** Les HDD modernes ont 64 à
256 Mo de cache. Un WD10SPZX 5400 tr/min affiche 254 Mo/s en zone de fin — physiquement
impossible pour ses plateaux, et son ratio ressort à 2,53 au lieu de ~0,45. C'est le seul
des 12 à contredire la signature. Le balayage réel devra lire par blocs **plus gros que
le cache**, ou à des offsets non prévisibles.

#### SMART NVMe : la cause est le mode RAID du contrôleur

Le message capturé est sans ambiguïté :
`Read NVMe Identify Controller failed: IOCTL_STORAGE_QUERY_PROPERTY(NVMe) failed, Error=1`.

Passer `-d nvme` n'y change rien : **c'est Windows qui refuse le passage de commande**,
pas smartctl qui se trompe de type. La corrélation est nette sur l'échantillon — les
machines qui exposent des périphériques `csmi` (contrôleur Intel RST en mode RAID) sont
exactement celles où le NVMe reste muet ; celle en AHCI répond parfaitement (Samsung 980,
série et usure 1 % lus sans peine).

**Conséquence pour le module, et elle est structurante** : sur une machine en RST, il n'y
aura **aucune donnée SMART** pour le disque système. Le test de surface devient alors la
seule source de vérité. C'est un argument pour le projet, pas contre : cela confirme que
lire SMART ne suffit pas — encore faut-il qu'il réponde.

#### Le disque que Windows montre n'est pas toujours un disque

Le volume `Optane+932GBHDD` (bus RAID) est un **composite** : cache Intel Optane devant un
TOSHIBA MQ04ABF100 5400 tr/min. La lecture brute voit 784 Mo/s en tête (le cache) puis
64 Mo/s (les plateaux), tandis que smartctl décrit le disque membre derrière `csmi0,0`.
Le module devra traiter ce cas explicitement : ce volume n'est pas testable comme un
disque, et son verdict porterait sur un objet qui n'existe pas physiquement.

Son numéro de série, `Optane_0000`, est un **gabarit de fabricant** — probablement
identique sur toutes les machines équipées. La règle de solidité rejette désormais les
séries terminées par quatre zéros.

---

### ✅ Phase 0 CLOSE — validation WinPE du 03/09/2026

5 exécutions sur **Hiren's BootCD PE** (Win11 22621), démarré par Ventoy. Les sept
points du verdict passent au vert :

| Point | Résultat en PE |
|---|---|
| `winpe_confirme` | ✅ marqueur `HKLM\SYSTEM\CurrentControlSet\Control\MiniNT` trouvé |
| **tkinter** | ✅ fenêtre + `mainloop`, Tcl 8.6.15 — **l'UI graphique est possible** |
| smartctl | ✅ opérationnel, 4 disques exploitables par run |
| accès disque brut / `NO_BUFFERING` | ✅ |
| n° de série lisible | ✅ les deux sources |
| rapport persistant | ✅ écrit sur la clé, jamais sur `X:` |

**Limite assumée** : ceci valide *Hiren's BootCD PE*, un WinPE garni (.NET, PowerShell),
pas un PE minimal construit à l'ADK. C'est l'environnement réellement utilisé en atelier,
donc c'est celui qui compte — mais la nuance est écrite plutôt que gommée.

#### 📐 Contrainte d'UI découverte : l'écran fait 800 × 600

C'est la résolution par défaut du PE tant qu'aucun pilote graphique n'est chargé.
**Toute l'interface de GhisdiagDisk doit tenir dans 800 × 600**, sans scroll horizontal.
C'est nettement plus contraint que Ghisdiag, dont l'en-tête compact vise déjà les 14"
(~1280 × 720, cf. v1.8.1). À prendre comme contrainte de conception, pas comme détail.

#### 🎯 Windows perturbe la mesure — chiffré, sur les mêmes disques physiques

Trois disques ont été mesurés dans **les deux environnements**, appariés par n° de série
(valeurs Windows issues des rapports du 02/09) :

| Disque | Environnement | Médiane par bloc (ms) | **Maximum** par bloc (ms) | max / médiane |
|---|---|---|---|---|
| WD5000AAKX | Windows | 8,4 / 9,6 / 16,8 | 16,6 / 26,1 / 37,0 | jusqu'à **2,7** |
| `WD-WCC2E5FK8EU6` | **WinPE** | 8,4 / 9,6 / 16,8 | 14,0 / 14,3 / 21,2 | jusqu'à **1,7** |
| HGST HTS541010A9E680 | Windows | 9,8 / 11,5 / 19,4 | 9,9 / 33,9 / 40,9 | jusqu'à **2,9** |
| `JD1009DM3B4RSK` | **WinPE** | 9,8 / 11,5 / 18,1 | 9,8 / 11,7 / 19,8 | jusqu'à **1,1** |
| TOSHIBA DT01ACA100 | Windows | 5,5 / 6,4 / 10,4 | 5,6 / 28,5 / 38,8 | jusqu'à **4,4** |
| `31QV335NS` | **WinPE** | 4,6 / 6,5 / 10,4 | 5,6 / 6,5 / 11,4 | jusqu'à **1,2** |

**Les médianes sont identiques d'un environnement à l'autre. Seuls les maximums
explosent sous Windows.** La médiane est robuste ; le maximum ne l'est pas — il capte
l'I/O de fond de l'OS.

Or `bloc_max` est précisément l'indicateur du secteur mourant. **Le balayage n'a donc de
sens qu'en WinPE** : sous Windows, il faudrait un seuil si haut (> 5× la médiane) qu'on
raterait les vrais défauts, ou si bas qu'on crierait au loup à chaque passage de
l'indexeur. C'est l'argument le plus fort en faveur de l'architecture bootable — et il
est maintenant chiffré, plus supposé.

**Seuil proposé pour le moteur de balayage** : en PE, un bloc au-delà de **3× la médiane
de sa zone** est une anomalie réelle (marge confortable au-dessus du 1,7 observé au pire
sur des disques sains). Sous Windows, refuser de conclure.

#### 🔎 La sonde a trouvé un vrai défaut, sur la clé Ventoy elle-même

`PhysicalDrive3` (Kingston DataTraveler, 7,8 Go) mesure **4,2 Mo/s et 363–378 ms par bloc
au milieu du support**, contre 44 Mo/s et 24 ms aux deux extrémités — et une exécution a
carrément rendu `[Errno 23] ReadFile`, soit une **erreur CRC**.

Deux lectures possibles, et je ne tranche pas : soit une zone réellement défaillante,
soit la contention avec l'ISO Hiren's que cette même clé servait pendant la mesure. La
constance des 363 ms sur les 16 blocs penche pour un défaut, l'erreur CRC aussi — mais
une clé USB sollicitée peut aussi produire les deux. **À recontrôler clé au repos, sur
une autre machine.**

Dans les deux cas, une règle en sort : **exclure aussi le périphérique depuis lequel le
PE a démarré**, et pas seulement celui qui porte la sonde — ici c'étaient deux clés
différentes (la sonde tournait depuis `PhysicalDrive2`, l'ISO était servi par
`PhysicalDrive3`). Mesurer un support occupé à alimenter le système donne des chiffres
qui ne décrivent pas le support.

### ✅ Phase 1 — le moteur de balayage T1 est écrit (03/09/2026)

Branche `claude/ghisdiaqdisk-balayage-t1-1c9efb`, empilée sur la PR #33. Livré : le
paquet `ghisdiagdisk/`, le lanceur `ghisdiagdisk_main.py`, `GhisdiagDisk.spec` (second
exe, même recette que `WinPEProbe.spec`) et `test_ghisdiagdisk_atelier.bat`. **49 tests
sans matériel** (faux disque + horloge virtuelle), 237 au total dans le dépôt. Build
PyInstaller vérifié (exe de 1,7 Mo, `smartctl.exe` embarqué).

**⚠️ Pas encore validé en atelier** : aucune exécution élevée sous Windows ni en WinPE.
Les constantes ci-dessous sont des choix raisonnés à partir des campagnes, pas des
mesures — c'est la validation qui dira si elles tiennent. La sonde
`atelier_winpe_probe.py` reste figée comme référence de terrain ; `rawdisk.py` en est
l'extraction réutilisable, avec les mêmes offsets et les mêmes pièges documentés.

| Module | Rôle |
|---|---|
| `rawdisk.py` | Win32 brut : énumération par index, identité IOCTL (offsets 12/16/20/24), partitions GPT/MBR lues sur le disque, `LecteurDisque` NO_BUFFERING + tampon VirtualAlloc, **double exclusion** porteur de l'exe / support de boot du PE (`PEBootRamdiskSourceDrive`) |
| `smart.py` | smartctl avec le **type conservé** (`-d`), dédoublonnage RST, attributs 5/187/196/197/198/199, détection « muet derrière RST », projection d'usure NVMe |
| `inventory.py` | clé composite à niveau de confiance, cascade mécanique/SSD, profil ZBR calibré, règles d'exclusion et avertissements |
| `niveaux.py` | T1/T2/T3, fichier-marqueur, **refus explicite** de T2/T3 (jamais de rétrogradation silencieuse vers T1) |
| `scan.py` | plan, moteur pur (lecteur + horloge injectables), checkpoint/reprise, synthèse, verdict |
| `cli.py` | console (lisible en 800×600), Ctrl+C = arrêt propre avec session écrite |

**Décisions prises en écrivant le moteur** (à confirmer par la validation) :

- **Plan** : express = 12 zones × 256 Mio (offset 0, fin *exacte* du disque, 10 réparties) ;
  standard = 48 × 1 Gio ; complet = 1 Gio contigus. Les zones dépassent le cache d'un
  disque (piège du WD10SPZX). Bloc de mesure = 1 Mio : un secteur mourant doit ressortir,
  pas se diluer.
- **Échauffement non mesuré avant chaque zone, lu AU-DELÀ de la fenêtre** (ou 64 Mio
  avant, pour la zone de fin) : la lecture anticipée du disque ne pré-charge donc pas la
  zone mesurée. Un seul échauffement en mode complet (têtes déjà en place).
- **Anomalie = bloc > max(3 × médiane de sa zone, 25 ms)**. Le plancher de 25 ms vise les
  SSD (médiane < 1 ms : 3× serait du bruit d'ordonnanceur) — **non calibré**, à vérifier
  sur NVMe en PE. Bloc > 500 ms = « mourant » → à remplacer.
- **Hors WinPE, refus de conclure sur les latences** (verdict *non concluant*, chiffres
  quand même dans la session). **Les secteurs illisibles et le débit concluent partout** :
  une erreur CRC est une erreur CRC, et les médianes sont identiques Windows/PE.
- **Secteur illisible** : bissection jusqu'au secteur physique (4 Kio), plafonnée à
  64 échecs par bloc (on ne martèle pas un disque mort), plages fusionnées et exprimées
  en LBA. **Arrêt de sécurité à 64 blocs illisibles** : « imager d'abord ».
- **Verdict** tri-état + non concluant, toujours avec ses raisons. À remplacer : secteur
  illisible, bloc mourant, SMART en échec, arrêt de sécurité. À surveiller : blocs lents,
  débit médian sous le plancher de la classe (NVMe 300, SSD 100, HDD 25 Mo/s —
  volontairement bas), SMART 5/197/198 > 0, erreurs média NVMe. La **portée** est
  toujours dite : « sain » en express signifie sain sur ~0,1 % de la surface.
- **Exclusions** : porteur de l'exe et boot PE (jamais), virtuel, composite `Optane+…`,
  clé USB amovible. Le NVMe derrière RST (bus RAID) **reste testable** — c'est la
  population visée — avec avertissement ; un disque en dock USB aussi, sans comparaison
  à la classe.
- **Lecture aléatoire** : 200 × 4 Kio à offsets tirés au sort (graine dans la session),
  p50 / p99 / max.
- **Session** : `rapports_disque\ghisdiagdisk_<clé>_T1_<horodatage>.json` à côté de
  l'exe (repli `Documents\Ghisdiag\disque`), écriture atomique après chaque zone,
  reprise refusée si la clé d'identité **ou** la taille diffèrent.
- **Pas d'UI graphique dans cette livraison** : la console tient en 800×600 et l'UI
  tkinter n'a de sens qu'une fois le moteur validé. Elle rappellera les mêmes fonctions.

**Prochaine étape — validation atelier, dans cet ordre :**

1. `test_ghisdiagdisk_atelier.bat --lister` **élevé** sous Windows : inventaire, clés,
   exclusions (le porteur doit être exclu, le disque système testable).
2. `py -m PyInstaller --clean --noconfirm GhisdiagDisk.spec`, copier `dist\GhisdiagDisk\`
   sur la clé CLAUDE, booter Hiren's PE : `--lister`, puis `--disque N --mode express`
   sur les trois disques déjà mesurés (WD5000AAKX, HGST HTS541010A9E680, Toshiba
   DT01ACA100). Attendu : médianes retombant sur celles du 03/09, **zéro anomalie**.
3. Un NVMe en PE : le plancher de 25 ms ne doit ni inventer ni masquer d'anomalie.
4. Un disque **connu défaillant** (la clé Ventoy suspecte, en dock, ou un HDD réformé) :
   le verdict doit basculer et le JSON localiser les plages.
5. Un Ctrl+C en pleine zone puis `--reprendre <session>` : les zones faites ne sont
   pas relues, le verdict final est complet.

---

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
| 0 | ✅ **Spike WinPE — TERMINÉ le 03/09.** Les 7 points au vert en PE | fait |
| 1 | ✅ **Moteur T1 ÉCRIT le 03/09** (balayage lecture + débit + latence + lecture aléatoire, modes express/standard/complet, session checkpointée et reprenable, CLI console). Reste la **validation atelier** — voir « Phase 1 » ci-dessus | gros |
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
