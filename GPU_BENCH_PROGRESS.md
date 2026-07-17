# Bench thermique GPU — Fichier de progression

> **Rôle de ce fichier** : mémoire de travail du chantier « bench thermique carte
> vidéo ». Il est mis à jour à chaque session (voir *Journal de session* en bas).
> Toute session future doit le lire en premier pour reprendre au bon endroit.
>
> Chantier ouvert le **2026-07-05**. Cible : nouvelle release (≥ 1.7.0).

---

## 🎯 Objectif

Étendre le bench thermique existant (aujourd'hui **CPU uniquement**) à la **carte
graphique** : chauffer le GPU de façon reproductible, mesurer son comportement
thermique (repos → charge → refroidissement) et objectiver un gain de maintenance
(nettoyage, changement de pâte/pads) — même logique avant/après que pour le CPU.

## 🔒 Décisions verrouillées (2026-07-05)

| Sujet | Décision | Pourquoi |
|---|---|---|
| **Génération de la charge GPU** | **Compute shader D3D11 piloté en ctypes/COM** | Aucun binaire ajouté, marche sur **tous** les GPU (NVIDIA/AMD/Intel/intégré). Fidèle à la philosophie « un seul exe qui marche partout ». Coût : le plus de code (interop COM en ctypes). |
| **Couverture fabricant** | **Tous fabricants dès la v1** | La charge (compute shader) est nativement vendor-neutral. Capteurs : NVML riche pour NVIDIA, LHM en repli pour AMD/Intel (données plus pauvres, assumé). |

---

## 🧱 État de l'existant (réutilisable)

- **[thermal_bench.py](thermal_bench.py)** — moteur : protocole 3 phases, échantillonnage,
  arrêt d'urgence, métriques, sauvegarde JSON, callbacks UI. Structure **agnostique**
  mais toute la logique concrète (charge, seuils, throttling, métriques) est **CPU**.
  Chaque échantillon capte déjà `gpu` / `gpu_load` / `gpu_fan`.
- **[collectors/gpu.py](collectors/gpu.py)** — lecture GPU **NVIDIA** via NVML
  (`nvml.dll`, sans élévation) : `available()`, `read()`, `hottest_temp()`. Donne
  aujourd'hui temp/charge/ventilo. À enrichir.
- **[collectors/cpu_load.py](collectors/cpu_load.py)** — générateur de charge CPU
  (multiprocessing). **Modèle** à répliquer pour `gpu_load.py` : script standalone +
  drapeau worker en mode figé (`--ghisdiag-*-worker`, géré dans `main.py`).
- **LibreHardwareMonitor** déjà embarqué → repli capteurs AMD/Intel.
- **UI bench** dans [main.py](main.py) : config intensité/kernel, courbes Canvas
  temps réel (séries CPU/GPU/disque déjà tracées), comparaison avant/après,
  avertissement de responsabilité avant test.
- **[thermal_compare.py](thermal_compare.py)** + **[report/generator.py](report/generator.py)** —
  comparaison de sessions + rapport HTML.

---

## ⚠️ Pièges techniques identifiés (à ne pas oublier)

1. **TDR (Timeout Detection & Recovery)** — 🔴 CRITIQUE. Si un seul `Dispatch`
   monopolise le GPU > ~2 s, Windows **réinitialise le pilote** (écran noir + reset).
   → Ne JAMAIS lancer un dispatch géant. On boucle plein de dispatches courts, avec
   synchronisation régulière (Flush + lecture d'une valeur) pour créer de la
   contre-pression et éviter d'empiler une file infinie.
2. **Bon GPU sur portable hybride (iGPU + dGPU)** — il faut **stresser exactement le
   GPU qu'on mesure**. → Énumérer les adaptateurs via DXGI (`CreateDXGIFactory`),
   choisir l'`IDXGIAdapter` cible et le passer à `D3D11CreateDevice`. L'identité de
   l'adaptateur (nom/LUID) doit correspondre à celle du capteur.
3. **WARP ≠ GPU** — en RDP / sans GPU exploitable, D3D11 peut retomber sur WARP
   (rasterizer **CPU**). → Exiger un device **hardware** ; si seul WARP est dispo,
   déclarer le bench GPU impossible avec un message clair.
4. **Shader HLSL** — pour ne dépendre de rien au runtime, **précompiler** le bytecode
   (DXBC) et l'embarquer en octets, plutôt que d'appeler `d3dcompiler_47.dll` à
   l'exécution (présent sur Win10/11 mais pas garanti partout).
5. **Écran qui rame pendant le bench** — chauffer le GPU d'affichage rend l'UI
   saccadée. Acceptable pendant un test, mais à **avertir** (réutiliser le disclaimer).
6. **Seuil d'urgence GPU** — un nombre fixe (~90 °C cœur) est moins fiable que la
   **raison de throttling** que NVML expose directement (`ClocksThrottleReasons` :
   thermal / power / hw slowdown). Combiner les deux quand dispo.

---

## 🗺️ Plan étape par étape (milestones)

> Ordre choisi pour **dé-risquer tôt** : d'abord la lecture (bénéfice immédiat,
> sert à vérifier la charge), puis le générateur de charge (le gros risque), puis
> le câblage moteur/UI, puis rapport et release.

### M0 — Cadrage ✅ *(fait 2026-07-05)*
- [x] Analyse de l'existant
- [x] Décisions verrouillées (charge D3D11 / tous fabricants)
- [x] Création de ce fichier de progression

### M1 — Lecture GPU enrichie (capteurs) ✅ *(fait 2026-07-05, sauf valid. atelier AMD/Intel)*
Bénéfice immédiat même sans le reste : le moniteur temps réel gagne les infos GPU.
- [x] Enrichir `collectors/gpu.py` (NVML) : **power (W)**, **clock SM/mém (MHz)**,
      **raison de throttling** (décodée : `throttle_thermal`/`throttle_power`/liste),
      **seuil slowdown** (`temp_slowdown_c`), **identité** (`name`/`uuid`/`index`).
      → hotspot/mem_temp restent `None` côté NVML (non exposés de façon fiable sur
      grand public) : ils viennent de LHM (voir ci-dessous). Clés présentes quand même.
- [x] Repli AMD/Intel via LHM : ajout de `gpu_name`, `gpu_core_clock`, `gpu_power`
      au flux `sensors.ps1` (le hotspot/temp/load/fan y étaient déjà).
- [x] API unifiée `collectors/gpu.py::list_gpus()` : NVIDIA via NVML, sinon 1 GPU
      agrégé via LHM. Identité stable = **`name`** (clé de jointure avec l'adaptateur
      DXGI de M2) ; `uuid` en complément côté NVIDIA.
- [x] Test standalone NVIDIA (`py -m collectors.gpu`) : Quadro P2000 → tous champs OK
      (power 6.5 W, clock SM/mém, slowdown 101 °C, throttle décodé). Flux LHM OK
      (`gpu_name`/`gpu_core_clock` 430 MHz/`gpu_power` 6.3 W + hotspot 49.2 °C).
      Consommateurs existants (moniteur, diagnostic, santé capteurs) non cassés.
- [x] **Validé en atelier sur 6 machines (2026-07-11)** : NVIDIA discret (NVML), AMD APU
      + Intel iGPU (LHM). Bug iGPU Intel (`list_gpus` vide) trouvé et corrigé — voir
      section « Résultats validation atelier » plus bas. Reste : 1 GPU **AMD discret**.

> ⚠️ **Unité ventilo hétérogène** : NVML rend le ventilo GPU en **%**, LHM en **RPM**.
> À traiter au moment des métriques (M3) / de l'affichage (M4) — ne pas comparer bêtement.

**Outil de validation atelier — CHARGE GPU (M2)** : [atelier_gpu_load.py](atelier_gpu_load.py)
+ [test_charge_gpu_atelier.bat](test_charge_gpu_atelier.bat) — double-clic : mesure la
temp au repos, chauffe le GPU 30 s (D3D11 compute, en interne), échantillonne la montée,
puis verdict + rapport `ghisdiag_charge_gpu_<hostname>_<date>.txt`. Sur iGPU (pas de temp
GPU) il regarde la temp package CPU. Testé sur dev (Quadro : 46→63 °C, +17 °C, 99 %,
sans TDR). **But atelier : confirmer chauffe + absence de TDR sur Intel/AMD.**

**Outil de validation atelier — CAPTEURS (M1)** : [atelier_probe.py](atelier_probe.py) +
[test_gpu_atelier.bat](test_gpu_atelier.bat) à la racine — double-clic sur le
`.bat` sur chaque machine d'atelier (depuis la clé USB, marche quel que soit le
lecteur). Écrit un rapport JSON horodaté par machine
(`ghisdiag_gpu_test_<hostname>_<date>.txt`) : NVML, `list_gpus()`, échantillon
LHM brut, contenu réel de `tools/`, état PawnIO. Ne plante jamais (sections
isolées). Trouve `py` ou `python` automatiquement ; écrit un message clair si
aucun des deux n'est installé. Testé sur la machine de dev (chemin OK, cas
« Python absent » simulé OK).

### M2 — Générateur de charge GPU (D3D11 compute) ✅ *(cœur fait/testé NVIDIA 2026-07-11)*
- [x] `collectors/gpu_load.py` calqué sur `cpu_load.py` : script standalone + mode
      worker `--ghisdiag-gpu-load-worker` **câblé dans `main.py`** (process unique,
      sans multiprocessing).
- [x] Interop ctypes/COM (appel par index de vtable, helper `_com`) :
      `CreateDXGIFactory1` → `EnumAdapters1`/`GetDesc1` → `list_adapters()` ;
      `D3D11CreateDevice` en `DRIVER_TYPE_UNKNOWN` sur adaptateur **matériel** choisi
      (jamais WARP), feature level 11_0.
- [x] Shader HLSL (boucle FMA `mad`) + `RWStructuredBuffer`/UAV + staging.
      ⚠️ **Déviation vs plan** : compilé au **runtime** via `d3dcompiler_47.dll`
      (composant Windows présent sur Win10/11), PAS de DXBC précompilé embarqué —
      je ne peux pas lancer `fxc` dans l'environnement de dev. Option ouverte :
      précompiler pour la release (retire la dépendance à d3dcompiler, même si c'est
      un composant OS). Ajouté à `available()` : la charge GPU exige les 3 DLL.
- [x] Boucle de dispatch **calibrée ~40 ms** (marge 50× sous TDR 2 s) + contre-pression
      par `CopyResource` → `Map(READ)` (borne la file GPU à 1). Calibrage : warm-up
      (JIT) puis montée en groupes jusqu'à un dispatch dominé par le calcul, extrapolé.
      Intensité 1..100 = rapport cyclique (sleep proportionnel après chaque dispatch).
- [x] Sélecteur d'adaptateur `_match_adapter` : index, sous-chaîne du nom, ou défaut =
      le dGPU avec le plus de VRAM (bon choix sur hybride).
- [x] **Test NVIDIA (Quadro P2000)** : charge **99 %** soutenue 30 s, clock 1721 MHz,
      power 7→57 W, temp **51→63 °C** monotone, **aucun TDR**, arrêt propre. Sélection
      d'adaptateur validée sur cette machine (hybride Quadro + Intel UHD 630).
- [x] **Validé atelier 3 vendors (2026-07-16)** — AUCUN TDR / crash nulle part :
      NVIDIA RTX 4060 (99 %, +12 °C GPU), AMD APU (96 %, +13 °C package, clock
      400→1825), Intel iGPU (clock 550→2000, 0→7 W, +3 °C package). Sélection
      d'adaptateur correcte partout. Détail : section « Résultats charge GPU atelier ».
- [ ] Intégration au moteur = **M3**.

### M3 — Généralisation du moteur ✅ *(fait + validé atelier 2026-07-17)*
- [x] `BenchConfig` : `target` (`cpu` | `gpu`), `gpu_adapter` (index/nom/None=auto),
      `gpu_emergency_temp_c` (défaut 90 °C). Défauts = comportement CPU inchangé.
- [x] Abstraction : interface `_ILoadGenerator` (Popen + taskkill /T communs) ;
      `_CpuLoadGenerator` (= ancien `_LoadGenerator`, alias conservé) +
      `_GpuLoadGenerator` (relance exe/script avec `--ghisdiag-gpu-load-worker`,
      `--adapter <index DXGI résolu>` pour stresser exactement le GPU mesuré).
      Fabrique `_make_generator(cfg)` choisie dans `_run()`.
- [x] Cible GPU : `_resolve_gpu_adapter()` (DXGI, échec immédiat si WARP only) +
      `_NvmlGpuSampler` (jointure par nom, clock/power/throttle NVML prioritaires
      sur LHM à chaque échantillon — leçon RTX 4060). Refus propre si aucune
      température GPU (iGPU non benchable).
- [x] Urgence GPU : temp ≥ min(seuil config, slowdown NVML − 3 °C) OU
      (`throttle_thermal` ET temp ≥ slowdown − 10 °C) — jamais le bit seul
      (faux positif au repos vu en atelier).
- [x] `compute_metrics` : bloc GPU (`gpu_plateau_c`, `gpu_delta_c`, `gpu_load_avg`,
      `gpu_power_max_w`, `gpu_hotspot_max_c`, `gpu_clock_max_mhz/drop_pct`,
      `gpu_slowdown_c`, `gpu_throttling`/`gpu_power_limited`, `gpu_cooldown_sec`)
      émis SEULEMENT si `target=gpu` → sortie des benches CPU strictement identique.
- [x] Échantillons enrichis (toutes cibles) : `gpu_hotspot`, `gpu_clock`,
      `gpu_power` (+ `gpu_throttle`/`gpu_slowdown_c` quand NVML). `gpu_fan` reste
      LHM/RPM — le % NVML n'est pas mélangé (unités hétérogènes).
- [x] Session JSON : `gpu_adapter` (index/nom/vendor/vram) quand cible GPU ;
      `list_sessions()` expose `target`.
- [x] Tests : `tests/test_thermal_bench.py` (unittest, 15 tests, fakes stream /
      générateur / NVML) — bench CPU rétro-compat strict (mêmes clés de métriques),
      bench GPU complet, repli LHM sans NVML, refus sans adaptateur / sans temp GPU,
      urgence (seuil dynamique, throttle confirmé, bit parasite à froid ignoré),
      throttling vs power-limit dans les métriques. `py -m unittest discover -s tests`.
- [x] **Validation dev (Quadro P2000)** — `atelier_thermal_bench_gpu.py` (pilote
      `ThermalBench(target="gpu")` de bout en bout, même chemin que l'UI M4) :
      44→70 °C (Δ23 °C), 99 % charge soutenue, clock NVML stable 1721 MHz
      (aucune chute), aucune urgence, session JSON standard écrite. Bout-en-bout
      validé sur materiel reel.
- [x] **Validation atelier multi-machines (2026-07-17, 4 machines)** — moteur M3
      complet via `atelier_thermal_bench_gpu.py`. AUCUN TDR / crash / urgence à tort.
      Détail : section « Résultats moteur GPU atelier » ci-dessous.
      - GTX 1060 3GB (desktop) : 36→61 °C (Δ23), 100 %, clock NVML 1949 stable, 99 W.
      - GT 1030 (desktop) : 35→55 °C (Δ18), 97 %, clock 1695 stable ; `power_limited`
        OK ; **power NVML absent** sur cette carte (`gpu_power_max_w=null`).
      - RTX 4060 Laptop (hybride) : 49→62 °C (Δ12), 99 %, clock 2055 stable. **Bit
        `sw_thermal` présent AU REPOS ignoré** → `gpu_throttling=false`, aucune urgence :
        exactement la leçon M1, prouvée dans le moteur M3.
      - Intel iGPU : **refusé proprement** (« aucune température GPU… GPU intégré »).
      - Reste souhaitable : un vrai **dGPU AMD discret** (toujours absent du parc).
- Reste AMD discret + un test avant/après réel (M5) pour boucler.

### M4 — UI onglet bench ⬜
- [ ] Sélecteur **cible CPU / GPU** (radio) dans l'onglet bench.
- [ ] Si GPU : dropdown adaptateur (si plusieurs GPU), presets d'intensité,
      réutiliser l'avertissement de responsabilité.
- [ ] Courbes temps réel : mettre la série GPU au premier plan quand `target=gpu`.
- [ ] Test visuel sur vraie machine.

### M5 — Rapport & comparaison GPU ⬜
- [ ] Étendre `thermal_compare.py` + `report/generator.py` aux métriques/séries GPU.
- [ ] Verdict clair avant/après GPU (« −8 °C en charge, throttling éliminé »).
- [ ] Garde-fou honnêteté : même protocole + même adaptateur pour comparer.

### M6 — Build & release ⬜
- [ ] Vérifier qu'aucun binaire n'est ajouté (d3d11.dll/dxgi.dll = composants OS ;
      shader précompilé embarqué).
- [ ] Bump version (orchestrator.py, report/generator.py, version_info.txt, manifest
      UAC de build.bat), CHANGELOG + RELEASE_NOTES.
- [ ] Build PyInstaller, vérif ProductVersion, SHA-256, release GitHub.
- [ ] Mettre à jour [ROADMAP.md](ROADMAP.md).

---

## 🧪 Résultats validation atelier (2026-07-11, 6 machines)

Tous : Windows 10/11, admin, Python 3.12/3.13, `tools/` (DLL LHM 0.9.6.0) présent, flux LHM OK.

| Machine | GPU | Source | temp | load | clock | power | throttle | `list_gpus` |
|---|---|---|---|---|---|---|---|---|
| MSI (hybride) | RTX 4060 Laptop | **nvml** | 47 | 0 | 1470 | 9.2 W | thermal+power=**true** ⚠️ | ✅ 1 (dGPU) |
| UTILISA (dev) | Quadro P2000 | **nvml** | 45 | 3 | 1075 | 19.7 W | false | ✅ 1 |
| DESKTOP-E35SBNU | AMD Radeon R3 (APU) | lhm | 60 | 0 | 203 | — | — | ✅ 1 |
| LAPTOP-SEKC8OHQ | AMD Radeon Graphics (APU) | lhm | — | 0 | 400 | — | — | ✅ 1 |
| DESKTOP-S8SFDM7 | Intel Graphics (iGPU) | lhm | — | — | 550 | 0 | — | ❌ **vide** → corrigé |
| LAPTOP-KLTOUQQO | Intel UHD (iGPU) | lhm | — | — | 200 | 0 | — | ❌ **vide** → corrigé |

**Ce qui marche :** NVML discret = données complètes (temp/power/clocks/throttle/identité).
Les ajouts `gpu_name`/`gpu_core_clock`/`gpu_power` remontent sur **tous** les vendors.

**Bug trouvé & corrigé :** `list_gpus()` renvoyait `[]` sur les **iGPU Intel** (ni temp ni
charge via LHM → garde-fou `_lhm_gpu()` trop strict). Relâché : on énumère dès qu'un
signal (temp/load/clock/power) existe. **À revérifier à la prochaine passe atelier.**

**Enseignements pour M3/M4 (importants) :**
1. **iGPU Intel = aucune température GPU via LHM.** → GPU non *benchable thermiquement*
   (normal : on ne re-paste pas un iGPU). M4 doit détecter l'absence de temp et
   griser le bench GPU avec un message clair, pas planter.
2. **`throttle_thermal` NVML peut être `true` AU REPOS** (RTX 4060 : true à 47 °C / 0 %
   de charge, seuil slowdown 91 °C). → **Ne jamais** conclure « souci thermique » sur ce
   seul bit : le combiner avec charge élevée ET temp proche de `temp_slowdown_c` (même
   leçon que le throttling CPU, cf. `THROTTLE_TEMP_FLOOR_C`).
3. **Clock NVML (SM) ≠ clock LHM (GPU Core) au repos** (RTX 4060 : 1470 vs 100 MHz ;
   Quadro : 1075 vs 1076, cohérent). → Pour la détection de bridage, comparer dans UNE
   seule source, sous charge (là où elles convergent).
4. **Hybride (iGPU+dGPU) :** `list_gpus()` ne renvoie que le **dGPU NVIDIA** (bon c: c'est
   la cible du bench). M2 (DXGI) devra explicitement sélectionner l'adaptateur NVIDIA.
5. **AMD discret non couvert par l'échantillon** : les 2 AMD testés sont des APU intégrés.
   Reste à valider sur une **vraie carte AMD Radeon discrète** (données via LHM only).

## 🔥 Résultats charge GPU atelier (2026-07-16, 3 machines)

| Machine | GPU ciblé | Charge max | Chaleur | Power | TDR |
|---|---|---|---|---|---|
| MSI (hybride) | RTX 4060 Laptop (dGPU) | 99 % | GPU 44→56 °C (**+12**) | 9→30 W | ❌ aucun |
| LAPTOP-FAISTEO3 | AMD Radeon APU | 96 % | package 50→63 °C (**+13**) | n/a | ❌ aucun |
| DESKTOP-S8SFDM7 | Intel iGPU | (clock 550→2000) | package 56→59 °C (**+3**) | 0→7 W | ❌ aucun |

**Le résultat clé : 0 TDR / 0 crash sur les 3 vendors** → le calibrage anti-TDR est robuste.
Sélection d'adaptateur correcte partout (dGPU sur hybride, WARP exclu). La charge « prend »
sur tous (utilisation ou clock/power qui montent).

**Enseignements pour M3/M4 :**
- **Clock LHM non fiable sous charge sur certains GPU** : RTX 4060 lue à **100 MHz** figé
  malgré 99 % / 30 W. → détection de bridage NVIDIA = **clock NVML** (fiable), jamais LHM.
- **iGPU = chaleur négligeable** (Intel +3 °C) : bench thermique GPU pertinent seulement
  sur **dGPU**. M4 : proposer/prioriser le dGPU, et pour un iGPU prévenir que la mesure
  se fait sur le package CPU et que le gain d'un repaste n'a pas de sens.
- **AMD APU : charge OK mais pas de temp GPU** → si un jour on bench un APU, s'appuyer sur
  la temp package CPU (edge case ; idéalement viser un vrai dGPU AMD, toujours pas dans le parc).
- **Puissance modérée sur gros dGPU** (RTX 4060 : 30 W sur ~100 W possibles) : le shader ne
  sature pas électriquement. +12 °C suffit pour un avant/après, mais RAFFINEMENT OPTIONNEL :
  noyau plus lourd (plus d'ALU / transcendantales) pour pousser les gros dGPU.

## 🧪 Résultats moteur GPU atelier (2026-07-17, 4 machines — M3)

Bench complet via `atelier_thermal_bench_gpu.py` (repos 15s → charge 60s →
refroidissement 30s), qui pilote `ThermalBench(target="gpu")` — le chemin exact
de l'UI M4. **Aucun TDR, aucun crash, aucune urgence déclenchée à tort.**

| Machine | GPU ciblé | idle→max | Δ | Charge | Clock NVML (chute) | Power | Verdict moteur |
|---|---|---|---|---|---|---|---|
| DESKTOP-FAJH22R | GTX 1060 3GB (desktop) | 36→61 °C | 23 | 100 % | 1949 MHz (1.3 %) | 99.2 W | sain, rien à signaler |
| DESKTOP-6U1TDAO | GT 1030 (desktop) | 35→55 °C | 18 | 97 % | 1695 MHz (0.7 %) | **null** | `power_limited` |
| MSI | RTX 4060 Laptop (hybride) | 49→62 °C | 12 | 99 % | 2055 MHz (0.0 %) | 31.4 W | `power_limited` |
| DESKTOP-S8SFDM7 | Intel iGPU | — | — | — | — | — | **refusé** (pas de temp GPU) |

**Validation la plus importante — RTX 4060 (MSI)** : NVML remonte
`["sw_power_cap","sw_thermal"]` **dès le repos** (49 °C / 0 % charge, slowdown 91 °C).
Le moteur garde `gpu_throttling=false` et **ne déclenche aucune urgence** : la temp
(max 62 °C) n'a jamais atteint le plancher `slowdown-10=81 °C`. C'est la preuve
terrain que la logique « ne jamais croire le bit thermique seul » (leçon M1) est
correctement implémentée dans le moteur M3. `power_limited` détecté sans le
confondre avec du thermique.

**Enseignements pour M4 (pas des bugs) :**
1. **`gpu_power_max_w` peut être `null`** (GT 1030 : NVML n'expose pas la puissance
   sur certaines vieilles/petites cartes, même si `sw_power_cap` remonte). L'UI M4
   doit afficher « n/a » proprement, pas 0 ni un vide trompeur.
2. **`gpu_cooldown_sec=null` sur les cartes desktop** : le refroidissement de 30 s
   *du script de test* est trop court pour redescendre à idle+5 °C (la RTX 4060
   laptop y arrive en 4.4 s). Métrique **correcte** (null = non atteint) ; en usage
   réel M4 le cooldown sera long (300 s comme le CPU). Rien à corriger.
3. **Sélection d'adaptateur sur hybride OK** : le MSI (iGPU Intel + RTX 4060) a bien
   ciblé la RTX 4060 dGPU. WARP/iGPU écartés.
4. **Chaleur modérée sur gros dGPU** confirmée (RTX 4060 : 31 W sur ~100 W, Δ12 °C ;
   RAFFINEMENT OPTIONNEL noyau plus lourd, cf. M2). Les cartes desktop plus petites
   (GTX 1060 : 99 W, GT 1030) chauffent mieux relativement.

## ❓ Questions ouvertes (à trancher en chemin)

- Cible **CPU/GPU exclusive** ou possibilité d'un mode **combiné** (chauffe totale) ?
  → démarrer exclusif (plus simple, plus sûr), combiné éventuellement plus tard.
- Seuil d'urgence GPU par défaut (valeur °C) — à caler avec les mesures atelier.
- Intensité GPU : presets équivalents aux presets CPU (modéré / fort) — à définir.

---

## 🗒️ Journal de session

### 2026-07-05 — Session 1 (cadrage)
- Audit de l'existant : moteur agnostique mais logique CPU ; `gpu.py` NVML de base ;
  `cpu_load.py` comme modèle de générateur ; LHM en repli.
- Décisions verrouillées avec l'utilisateur : **charge D3D11 compute via ctypes**,
  **tous fabricants dès la v1**.
- Pièges techniques documentés (TDR, GPU hybride, WARP, précompilation shader).
- Plan M0→M6 établi.

### 2026-07-05 — Session 2 (M1 : lecture GPU enrichie)
- `collectors/gpu.py` réécrit : NVML enrichi (power, clocks SM/mém, raisons de
  throttling décodées, seuil slowdown, identité name/uuid/index) + `list_gpus()`
  unifié avec repli LHM. `read()`/`hottest_temp()` rétro-compatibles (clés
  `name`/`temp`/`load`/`fan` conservées → diagnose_sensors & sensors_health OK).
- `collectors/sensors.ps1` : ajout `gpu_name`, `gpu_core_clock`, `gpu_power` au flux
  (repli tous vendors). Schéma mis à jour dans `sensors.py`.
- Validé sur Quadro P2000 (NVML + flux LHM). Découverte : **NVML ventilo en %,
  LHM en RPM** → à gérer en M3/M4.
- **Prochaine étape : M2 (générateur de charge GPU D3D11 compute).** C'est le gros
  morceau et le vrai risque — attention TDR / adaptateur hybride / WARP.

### 2026-07-11 — Session 3 (validation atelier M1)
- Sonde `atelier_probe.py` + `.bat` passée sur **6 machines** (NVIDIA discret, AMD APU,
  Intel iGPU, 1 hybride). Détail complet : section « Résultats validation atelier ».
- **Bug corrigé** : `list_gpus()` renvoyait `[]` sur iGPU Intel (garde-fou `_lhm_gpu()`
  trop strict, exigeait temp OU load ; les iGPU n'ont que clock/power). Relâché.
- 5 enseignements consignés pour M3/M4 (surtout : iGPU sans temp = non benchable ;
  `throttle_thermal` NVML faux-positif au repos ; clock NVML≠LHM au repos).
- Reste à couvrir : 1 **GPU AMD discret** (les AMD testés sont des APU intégrés).

### 2026-07-11 — Session 4 (M2 : générateur de charge GPU D3D11)
- `collectors/gpu_load.py` créé : pilote D3D11 compute en ctypes/COM (appel par index
  de vtable). Construit et testé **par étapes** sur le GPU réel de dev :
  1. Énumération DXGI + création device → OK (WARP écarté, dGPU sélectionné sur hybride).
  2. Shader compute + buffers/UAV + dispatch → OK.
  3. Calibrage anti-TDR (~40 ms/dispatch, 56662 groupes sur P2000).
  4. Charge réelle : **99 % soutenu, 51→63 °C, 7→57 W, sans TDR, arrêt propre.**
- Bug de calibrage corrigé (le 1er dispatch lent — JIT — trompait la mesure).
- Flag worker `--ghisdiag-gpu-load-worker` câblé dans `main.py`.
- Déviation assumée : shader compilé au runtime (`d3dcompiler_47.dll`) et non précompilé.

### 2026-07-16 — Session 5 (validation atelier M2, 3 vendors)
- `atelier_gpu_load.py` + `.bat` passés sur 3 machines : **NVIDIA RTX 4060, AMD Radeon
  APU, Intel iGPU**. **Aucun TDR, aucun crash** — validation majeure.
- Détail chiffré : section « Résultats charge GPU atelier ». M2 clos côté charge.
- Nouveaux enseignements M3/M4 : clock LHM figé sous charge sur RTX 4060 (→ clock NVML) ;
  iGPU chaleur négligeable ; option noyau plus lourd pour gros dGPU.
- Signalé par l'utilisateur : `python main.py` depuis les sources → « psutil non
  disponible » (deps pip non installées hors exe). À traiter (probablement bénin,
  mais vérifier qu'il n'y a pas un vrai traceback derrière). **À REGARDER PROCHAINE FOIS.**
- **Prochaine étape : M3** (généraliser `thermal_bench` : cible CPU/GPU, worker GPU avec
  relance figée + `taskkill /T`, urgence sur temp GPU, métriques GPU). Rappel : clock
  NVIDIA via NVML, pas LHM ; urgence GPU = throttle NVML + temp proche du seuil.

### 2026-07-17 — Session 6 (M3 : généralisation du moteur)
- ⚠️ Découverte : le travail M1/M2 n'était **pas commité** (worktree précédent).
  Importé et commité sur la branche `claude/thermal-bench-gpu-support-c8478f`
  (commit « base M1+M2 »), M3 par-dessus.
- `thermal_bench.py` généralisé CPU/GPU : voir la section M3 ci-dessus (cases cochées).
- Vérifié sur la machine de dev (Quadro P2000) : résolution DXGI → jointure NVML OK
  (slowdown 101 °C lu), args worker corrects, générateur disponible.
- 15 tests unitaires (`tests/test_thermal_bench.py`), tous verts.
- **Prochaine étape : M4** (UI onglet bench : radio CPU/GPU, dropdown adaptateur,
  griser si pas de temp GPU, courbe GPU au premier plan) + valider M3 en atelier
  (session GPU réelle complète). Le moteur est prêt : `BenchConfig(target="gpu")`.

### 2026-07-17 — Session 7 (validation dev + script atelier M3)
- Créé `atelier_thermal_bench_gpu.py` + `.bat` : pilote le moteur GÉNÉRALISÉ
  complet (`ThermalBench(target="gpu")`), pas juste le générateur de charge
  (contrairement à `atelier_gpu_load.py` de M2) — même chemin que prendra l'UI M4.
- **Testé sur la machine de dev (Quadro P2000)** : bout-en-bout OK. 44→70 °C,
  99 % charge soutenue 60 s, clock NVML 1721 MHz stable (aucune chute), aucune
  urgence ni abandon, session JSON standard écrite dans le dossier habituel.
  Bug cosmétique corrigé (tiret cadratin illisible sur certaines pages de code
  console Windows — remplacé par un tiret simple).
- **Reste à faire avant M4** : passer ce script sur d'autres machines d'atelier
  (au moins un 2e dGPU NVIDIA, AMD discret si dispo) pour confirmer que la
  résolution d'adaptateur et l'absence de faux-positifs d'urgence tiennent
  au-delà de la machine de dev.

### 2026-07-17 — Session 8 (validation atelier M3, 4 machines)
- `atelier_thermal_bench_gpu.py` passé sur **4 machines** : GTX 1060 3GB, GT 1030,
  RTX 4060 Laptop (hybride), Intel iGPU. **Aucun TDR, aucun crash, aucune urgence
  à tort.** Détail chiffré : section « Résultats moteur GPU atelier ».
- **Validation clé** : sur la RTX 4060, le bit `sw_thermal` présent DÈS LE REPOS
  (49 °C / 0 %) est correctement ignoré par le moteur → `gpu_throttling=false`,
  pas d'urgence. La leçon M1 (« ne pas croire le bit seul ») tient dans le moteur M3.
- iGPU Intel refusé proprement (message clair, pas de plante). Sélection dGPU
  correcte sur l'hybride. **M3 clos côté validation NVIDIA + iGPU.**
- 2 enseignements M4 (pas des bugs) : `gpu_power` peut être `null` (GT 1030) →
  afficher « n/a » ; `gpu_cooldown_sec=null` avec un cooldown court (normal, sera
  300 s en usage réel).
- Reste souhaitable : un vrai **dGPU AMD discret** (jamais dans le parc) + un
  avant/après réel (relève de M5).
- **Prochaine étape : M4 (UI).**
