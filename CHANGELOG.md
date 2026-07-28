# Changelog — Ghisdiag

Toutes les modifications notables de ce projet sont documentées ici.

---

## [2.0.1] — 2026-07-28

### 🌡️ Bench thermique — ne plus affirmer ce qui n'a pas été mesuré

Le bench pouvait rendre des conclusions qu'il n'avait jamais mesurées. Sur un
portable dont Windows ne remonte aucune fréquence CPU, le rapport affichait
« Throttling thermique : **non** » — une affirmation d'absence de défaut, alors
qu'aucune fréquence n'avait été relevée de tout le test. Un outil de diagnostic
qui rassure à tort fait suspecter du matériel sain, ou dédouane du matériel qui
chauffe.

- **Throttling : trois états au lieu de deux.** `throttling` et `power_limited`
  (et leurs équivalents GPU) valent désormais **oui / non / indéterminé**. Ils
  ne se déduisent que d'une comparaison de fréquences ; sans fréquence
  exploitable, l'outil dit qu'il ne sait pas. L'interface affiche
  « indéterminé » et explique pourquoi. Côté GPU, une réponse du pilote NVML
  suffit à conclure même sans fréquence lisible.
- **Les sessions déjà enregistrées sont relues correctement** : un
  `throttling: non` archivé sans aucune fréquence relevée est requalifié en
  indéterminé à l'affichage — inutile de refaire les tests passés.
- **La comparaison avant/après contrôle enfin les conditions de mesure.** Elle
  ne regardait que le protocole *demandé* (durées, intensité) et ignorait
  totalement ce qui s'était *réellement passé*. Sont désormais comparés et
  signalés :
  - le **noyau de charge** (`avx` / `python`), qui fait maintenant partie du
    protocole : ces deux charges ne dégagent pas la même chaleur ;
  - les **arrêts d'urgence**, **interruptions** et **refroidissements écourtés** ;
  - la **durée de charge réellement tenue** face à celle prévue — une charge
    coupée à 25 s sur 300 s n'a atteint aucun régime établi, son « plateau »
    n'est que le sommet d'une montée en température.
- Quand ces conditions ne sont pas comparables, le verdict ne chiffre plus de
  gain : il annonce **« comparaison non concluante »** et détaille pourquoi.
  Le rapport HTML gagne un tableau *« ce qui s'est réellement passé »*, affiché
  systématiquement — y compris quand tout va bien.
- **Plus de « plateau » sur une charge écourtée.** Le plateau et le ΔT étaient
  calculés sur le dernier tiers de la phase de charge. Sur un test coupé au bout
  de 25 s sur 300 prévues, ce « dernier tiers » n'était que le sommet d'une
  rampe : l'outil annonçait un régime établi qui n'avait jamais existé. Les deux
  valeurs sont désormais laissées vides, avec l'explication. La température
  **maximale**, elle, reste affichée — elle a bien été atteinte.
- **La limite de puissance (PL1/TDP) est enfin détectée.** Elle se déduisait
  d'une chute de fréquence entre le début et la fin de la charge — or sur un
  portable, le processeur est déjà retombé sur sa puissance soutenue au bout de
  30 secondes : les deux mesures étaient identiques et la limitation restait
  invisible. La comparaison se fait maintenant avec la **fenêtre turbo** du tout
  début de charge. Concrètement, un portable qui plafonne à 85 °C parce qu'il
  applique sa limite de puissance affiche enfin *« Normal — ce n'est pas un
  souci de refroidissement »* au lieu de laisser croire à une surchauffe.
- **Seuil d'arrêt d'urgence réglable** par la variable d'environnement
  `GHISDIAG_EMERGENCY_TEMP_C` (bornée à 60-99 °C, jamais au-delà du TjMax). Sur
  un portable Intel P-series, la première minute de charge se passe en turbo
  bien au-dessus de la puissance soutenue : couper à 95 °C empêchait d'atteindre
  le régime établi, donc de mesurer ce que le test est censé mesurer. Les quatre
  endroits de l'interface qui annonçaient « 95 °C » en dur affichent désormais
  le seuil réellement appliqué.

### 🌡️ Bench thermique — fréquences CPU sur les Intel récents

- **Les processeurs hybrides remontent enfin leur fréquence.** Sur Alder Lake et
  suivants (12ᵉ génération et plus), les capteurs se nomment `P-Core #N` et
  `E-Core #N` ; Ghisdiag ne cherchait que `CPU Core #N` et n'en trouvait aucun.
  Aucune fréquence n'était donc relevée, ce qui désactivait **silencieusement**
  toute la détection de throttling sur ces machines — tout en affichant quand
  même « Throttling : non ». Corrigé côté fréquences et températures.

---

## [2.0.0] — 2026-07-27

> **Ghisdiag change de format de distribution.** L'application n'est plus un
> exécutable unique mais un **dossier portable**, livré en archive `Ghisdiag.zip`.
> Ce changement casse l'habitude « je télécharge un .exe et je double-clique »,
> d'où le passage en version majeure — d'où aussi le reste de cette entrée, car
> ce format débloque plusieurs problèmes de fond.

### 📦 Distribution : passage en mode `onedir`

- L'archive `Ghisdiag.zip` (~34 Mo, soit la taille de l'ancien exe) se décompresse
  en un dossier `Ghisdiag\` contenant `Ghisdiag.exe` et son sous-dossier
  `_internal\`. **Garder le dossier entier** — l'exe seul ne démarre pas.
- **Pourquoi :** l'ancien format décompressait 34 Mo dans le `%TEMP%` de la machine
  cliente *à chaque lancement*. Sur clé USB en atelier, c'était le goulot
  d'étranglement de chaque démarrage, et ça laissait un dossier `_MEI` chez le
  client — parfois orphelin après un plantage. Le nouveau format ne décompresse
  rien : Windows charge les DLL directement depuis le dossier.
- Ce même schéma « je m'extrais dans TEMP puis je m'exécute » est celui des
  *droppers* : il pesait lourd dans le score heuristique des antivirus.

### 🛡️ Antivirus — réduction des faux positifs

Ghisdiag était signalé comme *trojan* par plusieurs moteurs. C'est un faux positif
structurel, documenté en détail dans le nouveau
[`docs/transparence-systeme.md`](docs/transparence-systeme.md) — document destiné
autant aux utilisateurs qu'aux analystes antivirus, et à joindre à tout signalement.

- **Sauvegarde WiFi : plus de mots de passe en clair par défaut.** L'export en
  clair reste disponible — il est indispensable pour restaurer après une
  réinstallation de Windows ou sur une autre machine — mais il demande désormais
  une confirmation explicite qui en énonce la conséquence. L'export en masse de
  clés WiFi en clair vers une archive est la signature comportementale exacte de
  la famille `PWS:Win32/WifiStealer`.
- **`upx=False`** — la compression UPX est un marqueur de packer qui coûtait des
  points de score, même sur un binaire sain.
- **Build public et vérifiable** — nouveau workflow GitHub Actions qui compile
  depuis le code source taggé et génère une **attestation de provenance SLSA
  signée**. N'importe qui peut vérifier qu'une archive publiée vient bien de ce
  code source : `gh attestation verify Ghisdiag.zip --repo ghislaindoucy/ghisdiag`.
- `Ghisdiag.spec` et `Ghisdiag.manifest` sont désormais **versionnés** et
  consommés tels quels par `build.bat` **et** par la CI : les deux compilent avec
  exactement les mêmes options.

### 🩹 Correctifs

- **UAC : le manifeste était inopérant depuis toujours.** PyInstaller réécrit le
  `<requestedExecutionLevel>` à partir de son paramètre `uac_admin` et forçait
  `asInvoker`, ignorant le `requireAdministrator` déclaré dans `Ghisdiag.manifest`.
  L'application compensait en se relançant elle-même en mode élevé — soit un
  **double lancement du process à chaque démarrage**, particulièrement coûteux
  depuis une clé USB. Corrigé par `uac_admin=True`.
- **Températures disque absentes au démarrage du moniteur.** La première lecture
  n'était déclenchée qu'au 5ᵉ tick, soit 10 s après l'ouverture ; les disques
  affichaient « N/A » pendant tout ce temps, alors que le CPU et le GPU ont un
  repli immédiat via le flux LHM. La lecture part maintenant dès le premier tick.
- **Températures disque retardées par la lecture CPU.** Le cache n'était publié
  qu'après le repli WMI de la température CPU — une requête qui coûte 1 s, et
  jusqu'à 6 s sur une machine sans PawnIO, où elle se déclenchait à *chaque*
  cycle. GPU et disques sont désormais publiés dès qu'ils sont disponibles,
  indépendamment du CPU.
- **Restauration WiFi : noms de profils lisibles.** La liste affichait les noms de
  fichiers préfixés par l'interface (`Wi-Fi 3-MonReseau`) au lieu des noms de
  profils réels.

### 🔧 Développement

- **Nouveau : `GHISDIAG_DEBUG=1`** bascule le journal en `DEBUG` et ouvre chaque
  session sur un bloc de contexte — version, exe gelé ou sources, chemin des
  ressources, élévation effective, et **quels modules optionnels n'ont pas pu
  s'importer, avec la cause exacte**. La plupart des chemins capteurs attrapent
  leurs exceptions et les tracent en `DEBUG` : sans ce commutateur, une panne
  silencieuse en atelier ne laissait aucune trace exploitable. Les journaux HTTP
  restent volontairement en `INFO` pour qu'aucune clé API ne se retrouve dans un
  fichier qu'on partagerait.

---

## [1.8.2] — 2026-07-24

> **Poser une question à l'IA.** En plus de l'audit automatique, tu peux
> maintenant joindre une **question précise** en rapport avec le poste — l'IA y
> répond en tête de rapport, puis produit l'audit complet comme d'habitude.

### 🤖 Question libre à l'IA

- **Champ question optionnel** (500 caractères) dans le panneau Analyse IA,
  visible seulement quand une clé API est configurée. Compteur de caractères en
  direct.
- La réponse apparaît dans une section **« Réponse à ta question » en tête du
  rapport IA**, argumentée sur les données réelles du diagnostic (commandes
  exactes si pertinent). La question posée est rappelée dans l'en-tête du rapport.
- **Garde-fou hors-sujet** : si la question ne concerne pas le poste ou son
  dépannage (recette de cuisine, culture générale…), l'IA la décline poliment en
  une phrase et poursuit l'audit normalement.
- Sans question, le comportement est strictement identique aux versions
  précédentes.

### 🩹 Correctif (re-build du 2026-07-24, version inchangée)

- **Bench thermique : cible GPU bloquée sur « Détection des cartes graphiques
  en cours… »** — quand la détection était très rapide (carte NVIDIA lue via
  NVML, ~50 ms), son résultat pouvait être publié avant que l'interface ne soit
  prête : il était alors perdu **définitivement**, et la cible GPU restait
  refusée jusqu'au redémarrage de l'application (le bench CPU, lui, n'était pas
  concerné). Constaté en atelier sur une machine NVIDIA RTX.
- La détection démarre désormais **après** l'interface, **réessaie** si celle-ci
  n'est pas encore prête, et **se relance automatiquement** à chaque bascule sur
  la cible GPU tant qu'aucun résultat n'est disponible : l'attente ne peut plus
  être définitive.

---

## [1.8.1] — 2026-07-22

> **Confort petits écrans** : l'interface s'adapte enfin aux portables 14" et
> aux écrans 1080p en mise à l'échelle Windows (125/150 %), où le bas des
> onglets se retrouvait coupé sous la barre des tâches.

### 🖥️ Interface adaptative

- **Tous les onglets sont désormais défilables** : Analyse et Bench thermique
  rejoignent Dépannage / WiFi / Setup. Une barre de défilement n'apparaît que
  si la fenêtre est trop courte pour tout afficher — sur grand écran, le journal
  et le graphe s'étirent comme avant.
- **En-tête compact** sous 800 px de hauteur utile (portables 14", mise à
  l'échelle Windows) : sous-titre masqué, logo réduit, liens sur une seule
  ligne, onglets resserrés → ~100 px rendus au contenu.
- **Fenêtre restaurée bornée à l'écran** : elle ne dépasse plus sous la barre
  des tâches quand on quitte le mode maximisé sur petit écran.

### 🐛 Corrections

- **Molette de défilement** : chaque panneau installait un gestionnaire global,
  si bien que la dernière zone construite captait la molette de toute
  l'application (faire défiler un onglet agissait sur un autre). Un routeur
  unique dirige maintenant la molette vers la zone réellement survolée.
- Factorisation des 6 zones défilantes dupliquées en un helper unique.

---

## [1.8.0] — 2026-07-19

> **Diagnostic encore plus parlant** : le rapport dit maintenant en une seconde
> **ce qui ralentit le PC** (top 3 priorisé), signale les **pilotes obsolètes
> ou non signés** avec la source de mise à jour, décompose un **démarrage lent
> phase par phase**, et compare **deux diagnostics dans le temps** — la machine
> s'améliore ou se dégrade ?

### 🚦 Résumé exécutif « Ce qui ralentit ce PC »

- **Top 3 des freins de performance** en tête du rapport HTML : constat chiffré
  + action recommandée pour chacun (disque mécanique, RAM insuffisante ou
  saturée, disque plein, SMART en échec, démarrage lent, surchauffe CPU,
  antivirus multiples, démarrage encombré, pilotes en erreur…).
- Priorisation par **impact perf ressenti** — les alertes sécurité restent dans
  « Points d'attention ».
- **Garde-fous honnêteté** : HDD + SSD → constat conditionnel (Windows est
  peut-être sur le SSD), disques USB exclus, mesures instantanées (CPU/RAM au
  moment du diagnostic) formulées comme telles.
- Les freins sont aussi **injectés dans le JSON** (`executive_summary`) :
  l'audit IA et l'historique les exploitent directement.

### 🔌 Pilotes obsolètes / non signés

- Chaque pilote remonte désormais sa **signature**, sa **classe** et sa
  **présence réelle** (les périphériques fantômes sont ignorés).
- **Pilotes non signés** sur matériel actif : alerte + tableau dédié.
- **Pilotes anciens (>5 ans)** sur les classes qui comptent (GPU, réseau,
  audio, stockage, USB, Bluetooth) avec colonne **« Où mettre à jour »** par
  type de matériel. Les pilotes fournis par Windows (datés 2006 volontairement)
  sont exclus — zéro faux positif.
- Alerte seulement si GPU/réseau est concerné ou à partir de 3 pilotes
  (garde-fou bruit).

### ⏱ Démarrage décomposé phase par phase

- Le dernier démarrage mesuré par Windows (journal Diagnostics-Performance)
  est décomposé en **5 familles** : noyau & session, pilotes & périphériques,
  services critiques, profil, bureau — avec barres de proportion et le travail
  en arrière-plan après l'affichage du bureau.
- **Piste de diagnostic** quand une phase domine un démarrage lent (ex. :
  « un pilote traîne au chargement — croiser avec les pilotes anciens »).

### 📈 Historique des diagnostics

- Nouveau bouton **« Historique… »** dans l'onglet Analyse : sélection de deux
  rapports JSON de la même machine → **la machine s'améliore ou se dégrade ?**
- **Freins résolus / apparus / persistants**, 12 chiffres clés comparés (boot,
  BSOD, erreurs matérielles, espace disque, pilotes…), **usure SMART suivie
  disque par disque** (appariement par n° de série — un disque remplacé n'est
  pas une « dégradation »).
- **Verdict pondéré honnête** : seuls les freins et les métriques durables
  comptent — jamais les mesures instantanées. Rapport HTML dédié, imprimable.
- **Garde-fou identité** : même machine exigée (n° de série BIOS, hostname en
  repli). Fonctionne avec les rapports JSON des versions précédentes.

---

## [1.7.0] — 2026-07-17

> **Bench thermique GPU** : le bench avant/après s'étend à la **carte graphique**
> — chauffe reproductible du GPU (compute shader Direct3D 11, tous fabricants),
> mesure NVML fiable sous charge, comparaison et rapport dédiés. Validé en
> atelier sur NVIDIA discret (RTX 4060, GTX 1060, GT 1030, Quadro P2000),
> AMD APU et Intel iGPU — **aucun TDR, aucun crash**.

### 🎮 Bench thermique GPU

- **Cible CPU / GPU** dans l'onglet bench : nouveau sélecteur + choix de la
  carte graphique (« Auto » = carte dédiée la plus grosse ; les iGPU sans
  capteur sont écartés d'office avec un message clair — un iGPU partage le
  refroidissement du CPU, le bench n'y a pas de sens).
- **Charge GPU vendor-neutral** : compute shader Direct3D 11 piloté en
  ctypes/COM — fonctionne sur NVIDIA / AMD / Intel **sans aucun binaire
  ajouté** (d3d11/dxgi/d3dcompiler sont des composants Windows). Dispatches
  courts calibrés (~40 ms) : aucune réinitialisation de pilote (TDR) sur tout
  le parc de test.
- **Mesures fiables sous charge** : session NVML persistante sur le GPU ciblé
  (température, clock, puissance, **raison de bridage du pilote**) — la clock
  LibreHardwareMonitor peut rester figée sous charge sur NVIDIA ; repli LHM
  automatique sur AMD/Intel.
- **Arrêt d'urgence intelligent** : coupure avant le seuil de bridage
  constructeur (90 °C au plus, abaissé selon le seuil slowdown NVML), ou si le
  pilote signale un bridage thermique confirmé par la température — le bit
  seul peut être un faux positif au repos (vu en atelier sur RTX 4060).
- **Métriques GPU** : ΔT, plateau, max, hotspot, clock max + chute (source
  NVML), puissance, throttling **thermique** distingué de la **limite de
  puissance** (normale), temps de retour au calme.
- **Comparaison avant / après GPU** + **rapport HTML dédié** : verdict chiffré,
  cartes de gains (dont hotspot — révélateur du contact pâte/pads), courbes
  superposées. Garde-fous : protocole identique **et même carte** exigés.
- **Liste des sessions filtrée CPU | GPU** : les benchs des deux familles ne se
  mélangent plus dans la liste ni dans la comparaison.
- Relevés temps réel adaptés à la cible (GPU : temp / charge / MHz / W) et
  courbe GPU au premier plan pendant un bench GPU.

### 🌡️ Capteurs GPU enrichis (toutes fonctions)

- Lecture NVIDIA via **NVML** enrichie : puissance, fréquences SM/mémoire,
  raisons de bridage décodées, seuil slowdown, identité.
- Flux LibreHardwareMonitor : ajout de `gpu_name`, `gpu_core_clock`,
  `gpu_power` (tous fabricants) ; énumération corrigée sur les iGPU Intel.

---

## [1.6.6] — 2026-07-02

> Correctif d'**accessibilité de l'interface** sur les laptops à petit écran et
> en **mise à l'échelle Windows 125 %/150 %** : plus aucun bouton ni contrôle
> coupé hors de la fenêtre. Suite au signalement du bouton « Ajouter les icônes
> du bureau » invisible à l'installation d'un PC neuf.

### 🐛 Correctifs — accessibilité / affichage

- **Setup › PC Neuf** : le panneau devient défilable. Le bouton « Ajouter les
  icônes du bureau » et le journal restaient coupés hors écran sur petit écran
  ou en forte mise à l'échelle.
- **Bench thermique** : les contrôles du bas (« Comparer avant/après », liste des
  sessions) sont réservés en premier — c'est désormais le graphe qui rétrécit,
  plus eux qui disparaissent.
- **Fenêtres Configuration IA, mise à jour winget et attente d'analyse** : taille
  dictée par leur contenu au lieu d'une taille figée — elles restent entièrement
  visibles quelle que soit la mise à l'échelle de l'écran.
- **Fenêtre Licences** : le bouton « Fermer » reste toujours accessible même
  fenêtre très rétrécie.

---

## [1.6.5] — 2026-06-28

> Fiabilité des **capteurs** et du **bench thermique** sur tout type de machine,
> et nouveau **test de stabilité (charge AVX)**. Validée sur parc réel (Intel
> Coffee Lake, AMD Ryzen Zen 5) à l'issue des pré-releases 1.6.5-beta.1 à beta.3.

### 🌡️ Capteurs — robustesse tout-terrain

- Suivi de température **fiable sur n'importe quel CPU** : anti-freeze (watchdog
  qui tue un backend figé), backend LibreHardwareMonitor remplaçable sans
  recompiler, **GPU via NVML** et **disques via smartctl** (sans dépendre de LHM).
- **Mapping température AMD** (Tctl/Tdie) — corrige les Ryzen récents (Zen 5).
- **Température CPU fluide** dans le moniteur temps réel (flux capteurs persistant
  au lieu d'une relecture complète toutes les 10 s) ; repli ACPI conservé.
- **Santé capteurs visible** : raison affichée quand la température CPU manque
  (PawnIO absent, console non élevée…) + section **« Capteurs »** dans le rapport.

### 🔥 Bench thermique — test de stabilité

- **Mode « Stabilité (AVX max) »** : charge AVX (numpy/BLAS) qui pousse le CPU
  comme un torture-test ; repli automatique sur la charge Python si numpy absent.
- La charge **ne déborde plus** sur le refroidissement (arrêt de tout l'arbre de
  processus).
- Distinction **throttling thermique** (vrai souci de refroidissement) vs
  **limite de puissance (PL1/TDP)** (normal — explique pourquoi la température
  plafonne).

### 🐛 Correctif

- Version affichée dans le rapport HTML de nouveau correcte (était figée à 1.6.0).

---

## [1.6.5-beta.3] — 2026-06-28 · pré-release de test

> Ajoute un vrai **test de stabilité (charge AVX)** et corrige plusieurs points
> du bench thermique repérés en test réel. **Remplace la 1.6.5-beta.2.**

### 🔥 Bench thermique — test de stabilité

- **Mode « Stabilité (AVX max) »** (nouveau choix d'intensité) : charge AVX via
  numpy/BLAS (~80 GFLOP/s/cœur, ~4400× plus de calcul vectoriel que la charge
  Python) — pousse le CPU comme un torture-test. Repli automatique sur la charge
  Python si numpy est absent.

### 🐛 Correctifs bench

- **La charge ne déborde plus sur le refroidissement** : à l'arrêt, on tue tout
  l'arbre de processus (les sous-processus de calcul restaient actifs ~30 s,
  faussant le refroidissement et le graphe).
- **Plus de faux « throttling thermique »** : la baisse de fréquence de fin de
  turbo Intel (PL2→PL1) à température modérée n'est plus prise pour du throttling
  thermique (seuil relevé à 90 °C, proche du TjMax).
- **Nouvel indicateur « limite de puissance (PL1/TDP) »** : explique pourquoi la
  température plafonne à charge soutenue (le CPU bride sa puissance — normal, ce
  n'est pas un défaut de refroidissement).

---

## [1.6.5-beta.2] — 2026-06-28 · pré-release de test

> Correctifs de la beta.1 après tests : la température CPU mettait beaucoup de
> temps à s'afficher / se rafraîchir. **Remplace la 1.6.5-beta.1.**

### ⚡ Performance — moniteur temps réel

- **Température CPU en continu** : le moniteur ouvrait LibreHardwareMonitor (et
  rechargeait toutes les DLL) à *chaque* rafraîchissement, toutes les 10 s
  seulement → première valeur très tardive et affichage en retard. Il utilise
  désormais un **flux capteurs persistant** (LHM ouvert une seule fois, watchdog
  anti-freeze) : la température CPU se rafraîchit toutes les ~2 s.
- GPU (NVML) et disques (smartctl) restent lus en arrière-plan, sans relancer LHM.

### 🐛 Correctif

- **Repli température CPU via ACPI** rétabli indépendamment du GPU/disque : sur
  une machine sans PawnIO, la température CPU (zone thermique ACPI) n'était plus
  affichée dès qu'un GPU ou un disque était détecté (régression vs 1.6.4).

---

## [1.6.5-beta.1] — 2026-06-27 · pré-release de test

> Version **beta** destinée aux tests sur parc varié. Non marquée « Latest » :
> la 1.6.4 reste la version stable. Objectif : valider la robustesse des
> capteurs et du bench thermique sur un maximum de CPU différents.

### 🌡️ Capteurs & bench thermique — robustesse tout-terrain

- **Anti-freeze** : le flux de capteurs est surveillé par un watchdog qui tue un
  backend figé (CPU non supporté, probing bloquant) au lieu de geler l'appli ; le
  bench vérifie que la température CPU répond **avant** de démarrer.
- **Backend LibreHardwareMonitor remplaçable** sans recompiler (dossier `tools`
  override) — permet d'essayer une DLL plus récente pour un CPU très récent.
- **GPU NVIDIA via NVML** et **disques via smartctl**, en mode utilisateur, sans
  dépendre de LHM (plus tout-terrain).
- **Mapping température AMD** (`Core (Tctl/Tdie)`, `CCDx (Tdie)`) — corrige
  l'absence de température sur les Ryzen récents (ex. Zen 5).
- **Probing disque LHM désactivé** (figeait sur certains Intel type J1900) ; les
  disques passent par smartctl.

### 🩺 Santé capteurs visible

- Le moniteur affiche désormais **pourquoi** une température CPU est absente
  (« PawnIO absent », « console non élevée », « CPU non supporté »…) au lieu d'un
  « N/A » muet.
- Nouvelle section **« 🌡 Capteurs »** dans le rapport HTML (température CPU,
  élévation, PawnIO, version du backend, sources GPU/disque).

### 🐛 Correctif

- La version affichée dans le rapport HTML était restée bloquée à 1.6.0 ; elle
  suit de nouveau la version réelle.

---

## [1.6.4] — 2026-06-22

### 🐛 Correctif

- **Faux positif « Corruption NTFS »** corrigé : l'événement `Microsoft-Windows-Ntfs`
  **ID 98** (« volume sain », niveau Info), émis par l'auto-vérification de
  routine, n'est plus compté comme une corruption. Seuls **55 / 57 / 137**
  (corruption / risque réels) sont retenus.

---

## [1.6.3] — 2026-06-22

### ⚖️ Conformité licences tierces

- Ajout de **THIRD-PARTY-NOTICES.md** (attribution complète : smartmontools/GPL,
  PawnIO/GPL, LibreHardwareMonitorLib + DiskInfoToolkit + BlackSharp.Core/MPL,
  HidSharp/Apache, Microsoft .NET System.*/MIT) et du dossier `licenses/` avec
  les textes officiels (MIT, Apache-2.0, MPL-2.0, GPL-2.0).
- Nouveau dialogue **« Licences & mentions légales »** accessible depuis l'en-tête.
- Licences embarquées dans l'exe (`build.bat`) et attachées automatiquement aux
  releases (`finalize_release.ps1`).

---

## [1.6.2] — 2026-06-22

### 🔗 Accès au projet

- Lien **« Code source & releases sur GitHub »** ajouté dans l'en-tête de
  l'application (sous le lien de soutien) : ouvre le dépôt GitHub.

### 📖 Documentation

- **README** mis à jour pour refléter toutes les fonctionnalités actuelles
  (bench thermique, dépannage / PC Neuf, fiabilité, IA multi-fournisseurs).
- Correction de références obsolètes (liens/badge en v1.4.0, chemin de build
  `PlanetDIag`).

---

## [1.6.1] — 2026-06-21

### 🎨 Interface & branding

- Le **logo chat** remplace l'ancienne planète stylisée dans l'en-tête de l'application
  (image native Tk, sans dépendance PIL ajoutée ; repli sur la planète si l'asset manque).
- Lien de soutien **« ☕ Offrez-moi un café »** (PayPal) ajouté dans l'en-tête de l'app,
  le README et la notice d'utilisation.

### 🧹 Maintenance

- Nouvelle action **« Vider les journaux Windows »** (onglet Dépannage → Réparation
  système) : efface les journaux d'événements lus par le diagnostic pour repartir d'un
  historique vierge après une réparation.

### 📖 Documentation

- **Notice d'utilisation illustrée** au format PDF couvrant l'ensemble des fonctionnalités
  (les onglets, le bench thermique, la configuration des clés API, le glossaire).

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
- Timeout et `reasoning_effort` réglables par fournisseur : OpenAI (gpt-5.5,
  modèle de raisonnement) tourne en effort « low » avec un timeout élargi pour
  éviter une expiration sur les audits longs

### 🌡️ Améliorations du bench thermique

- **Avertissement de responsabilité** avant chaque test : rappelle que les sécurités
  (arrêt à 95 °C, arrêt manuel) réduisent mais n'éliminent pas le risque, et que
  selon l'état du matériel un dommage reste possible — démarrage sous la
  responsabilité de l'utilisateur
- **Durée de charge personnalisable** : en plus des presets (Court / Standard / Long),
  une option « Personnalisé… » permet de saisir une durée en minutes (1 à 30). La
  comparaison avant / après refuse les protocoles différents, garantissant une durée
  identique des deux côtés

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
