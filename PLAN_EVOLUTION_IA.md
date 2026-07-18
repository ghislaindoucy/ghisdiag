# Ghisdiag — Plan d'évolution : maintenance par IA & Diagnostic v2

> **Rôle de ce fichier** : plan directeur destiné à être lu et exécuté par des
> instances d'IA (Claude Code ou autre) travaillant sur Ghisdiag. Il se lit comme
> une suite de chantiers autonomes. Chaque chantier a un objectif, des étapes, des
> fichiers concernés et des **critères d'acceptation** vérifiables.
>
> **Toute session IA qui ouvre ce plan doit :**
> 1. Lire ce fichier en entier, puis [ROADMAP.md](ROADMAP.md) (état des releases).
> 2. Vérifier dans la section *Journal* (en bas) où en est le chantier visé.
> 3. Travailler sur **un seul chantier à la fois**, sur une branche dédiée.
> 4. Mettre à jour le *Journal* avant de terminer la session.
>
> Rédigé le **2026-07-18** (version courante du logiciel : **1.7.0**).

---

## 📌 Contexte produit (à ne jamais perdre de vue)

Ghisdiag est un outil de **diagnostic et maintenance Windows pour technicien SAV** :
un seul exécutable PyInstaller `--onefile` (~19 Mo), zéro dépendance sur la machine
cliente, rapport HTML remis au client en fin d'intervention. Public : ateliers de
réparation, machines hétérogènes (du laptop Intel 8e gen au desktop Zen 5).

**Invariants produit** (toute évolution doit les respecter) :
- **Un seul exe qui marche partout** — pas de binaire lourd ajouté sans nécessité,
  pas de SDK Python pour les API IA (tout en `requests`), composants Windows natifs
  privilégiés (D3D11, WMI, PowerShell 5.1).
- **Offline d'abord** — le diagnostic complet fonctionne sans Internet ; l'IA est
  un bonus optionnel.
- **Zéro problème inventé** — chaque alerte a une preuve ; les faux positifs sont
  des bugs (cf. correctifs NTFS 98 en v1.6.4, démarrage lent en v1.3.0).
- **Validation atelier obligatoire** — rien n'est « livré » tant que Ghislain n'a
  pas validé sur machines réelles. L'IA prépare, l'humain valide sur le terrain.
- **Langue** : code commenté et UI en **français**, messages orientés technicien.

**Architecture actuelle** :

```
main.py (~5 460 lignes)   UI tkinter monolithique (thème Catppuccin Mocha), 4 onglets
orchestrator.py           exécution parallèle des collecteurs PS1 (~20 s)
collectors/*.ps1          collecte PowerShell (pattern Safe-Get partagé, _common.ps1)
collectors/*.py           capteurs (LHM, NVML, PawnIO, smartctl), charge CPU/GPU, moniteur
report/generator.py       rapport HTML/JSON + règles d'alertes déclaratives (~1 400 lignes)
ai_analyzer.py/ai_report.py  audit IA multi-fournisseurs (5 API, requests pur)
thermal_bench.py/thermal_compare.py  bench thermique CPU/GPU + comparaison avant/après
prefs.py / security.py    préférences persistées, chiffrement clés, UAC
tools/                    binaires embarqués (LHM DLL, smartctl, PawnIO)
tests/                    2 fichiers (bench thermique uniquement)
```

---

# PARTIE A — Système de maintenance du programme par des IA

**But** : faire de Ghisdiag un dépôt sur lequel une instance de Claude Code peut
travailler efficacement, en sécurité, avec le minimum de contexte à redécouvrir à
chaque session — et où l'humain n'intervient que là où il est irremplaçable
(décisions produit, validation atelier).

### Constat honnête (2026-07-18)

Ce qui aide déjà une IA aujourd'hui :
- Docs vivantes de qualité (README, ROADMAP, CHANGELOG, notes de release).
- Le pattern « fichier de progression de chantier » ([GPU_BENCH_PROGRESS.md](GPU_BENCH_PROGRESS.md),
  jalons M0→M6, décisions verrouillées, pièges, journal de session) — **il a fait
  ses preuves sur le chantier GPU, c'est le modèle à généraliser.**
- Conventions homogènes (Safe-Get dans les collecteurs, sessions JSON horodatées).

Ce qui freine une IA aujourd'hui :
- **Pas de `CLAUDE.md`** : chaque session redécouvre les pièges (PowerShell 5.1,
  `--onefile` et réextraction des workers, TDR GPU, antivirus…).
- **`main.py` monolithique (5 460 lignes)** : toute modification UI passe par un
  fichier géant → éditions risquées, conflits, contexte englouti.
- **Couverture de tests quasi nulle** hors bench thermique : les collecteurs, le
  générateur de rapport et les règles d'alertes ne sont pas testables sans une
  vraie machine.
- **Pas de CI** : rien ne vérifie qu'un commit casse le build de l'exe ou les tests.
- La validation matérielle (capteurs, bench) exige l'atelier — il faut donc un
  protocole clair de **hand-off IA → humain**.

---

## Chantier A1 — `CLAUDE.md` : la mémoire de travail permanente

**Priorité : 1 (à faire en premier, quelques heures de travail).**

**Objectif** : qu'une session neuve soit opérationnelle en 2 minutes de lecture.

**Étapes** :
1. Créer `CLAUDE.md` à la racine avec, dans cet ordre :
   - Mission produit + invariants (copier la section « Contexte produit » ci-dessus).
   - Carte de l'architecture (1 ligne par fichier majeur).
   - **Commandes** : lancer l'app (`python main.py`, droits admin requis pour
     certains collecteurs), tests (`python -m pytest tests/ -v`), build (`build.bat`),
     release (`finalize_release.ps1`).
   - **Pièges connus** (liste vivante, à enrichir à chaque chantier) :
     - PowerShell **5.1** cible (pas de `&&`, pas d'opérateur ternaire, encodage
       UTF-16 par défaut) ; pattern Safe-Get obligatoire dans tout collecteur.
     - PyInstaller `--onefile` : tout sous-processus Python réextrait le bundle →
       workers via drapeaux `--ghisdiag-*-worker` gérés en tête de `main.py`,
       ou runspaces PowerShell.
     - TDR GPU : jamais de dispatch D3D11 > ~2 s.
     - Faux positifs = bugs : toute nouvelle règle d'alerte exige un seuil justifié
       et un événement témoin réel.
     - Antivirus : l'exe non signé déclenche des faux positifs (cf.
       [docs/antivirus-guide.md](docs/antivirus-guide.md)) — ne pas ajouter de
       comportements « suspects » (auto-modification, téléchargements).
   - Processus de chantier (renvoi vers A5) et exigence de validation atelier.
2. Y déclarer la règle : *« à chaque piège découvert en session, l'ajouter à la
   liste avant de terminer »*.

**Critères d'acceptation** : le fichier existe, tient en < 250 lignes, et une
session test (nouvelle instance) sait lancer app + tests + build sans autre lecture.

---

## Chantier A2 — Harnais de vérification : rendre le diagnostic testable sans machine réelle

**Priorité : 2. C'est le chantier qui débloque tout le reste** — sans lui, une IA
ne peut pas prouver qu'elle n'a rien cassé.

**Objectif** : découpler « collecte » (nécessite une vraie machine Windows) de
« interprétation » (règles d'alertes, rapport, scoring) pour tester la seconde
sur des données enregistrées.

**Étapes** :
1. **Corpus de machines** : créer `tests/fixtures/machines/` contenant des sorties
   JSON réelles anonymisées des collecteurs (une par profil : laptop sain, desktop
   avec BSOD, machine au disque SMART dégradé, machine sans capteurs…).
   - Ajouter un mode **`--dump-fixture`** à `orchestrator.py` : exécute la collecte
     et enregistre le JSON brut anonymisé (hostname, users, SSID, clés produits
     masqués). Ghislain le lance sur les machines de l'atelier → le corpus grossit
     naturellement à chaque intervention intéressante.
2. **Tests des règles d'alertes** : `tests/test_report_rules.py` — charger chaque
   fixture, exécuter `report/generator.py`, vérifier les alertes attendues
   (déclarées dans un petit YAML/JSON à côté de chaque fixture : `expected_alerts`).
   Chaque faux positif corrigé par le passé (NTFS 98, démarrage lent, comptage
   fantôme) devient un **test de non-régression**.
3. **Tests de parsing des collecteurs** : les `.ps1` sortent du JSON → vérifier
   avec de vraies sorties enregistrées que le parsing Python ne casse pas sur les
   cas limites (champs absents, listes vides, accents/encodage).
4. **Smoke test app** : `tests/test_smoke.py` — importer `main.py` sans ouvrir la
   fenêtre (factoriser un `build_app(headless=True)` si besoin), instancier le
   générateur de rapport sur une fixture, vérifier que le HTML produit contient
   les sections attendues.
5. **Mode selftest de l'exe** : `Ghisdiag.exe --selftest` → vérifie présence des
   binaires embarqués (smartctl, LHM DLL), exécute un collecteur trivial, sort
   code 0/1. Utilisé par la CI post-build et par Ghislain après chaque build.

**Critères d'acceptation** : `python -m pytest tests/ -v` passe en < 60 s sans
droits admin ni matériel particulier ; ≥ 4 fixtures machines ; chaque faux positif
historique a son test.

---

## Chantier A3 — Découpage de `main.py`

**Priorité : 3 (après A2, pour refactorer sous protection des tests).**

**Objectif** : passer de 1 fichier de 5 460 lignes à des modules < 800 lignes,
pour que les sessions IA éditent localement sans risque de conflit ni de contexte
saturé.

**Étapes** (mécanique, sans changement de comportement) :
1. Extraire le thème et widgets partagés → `ui/theme.py`, `ui/widgets.py`.
2. Extraire chaque onglet → `ui/tab_analyse.py`, `ui/tab_depannage.py`,
   `ui/tab_wifi.py`, `ui/tab_setup.py`, `ui/tab_bench.py`.
3. Extraire les dialogues (config IA, licences) → `ui/dialogs/`.
4. `main.py` ne garde que : gestion des drapeaux workers (`--ghisdiag-*-worker` —
   **attention, doit rester tout en haut, avant les imports lourds**), création de
   la fenêtre, assemblage des onglets.
5. Mettre à jour `Ghisdiag.spec` (hidden imports éventuels) et vérifier le build.

**Critères d'acceptation** : aucun module > 800 lignes ; l'exe se build et se
lance ; smoke tests verts ; comportement identique (vérification atelier rapide).

---

## Chantier A4 — CI GitHub Actions (Windows)

**Priorité : 4.**

**Objectif** : chaque push/PR est vérifié automatiquement ; une session IA voit
immédiatement si elle a cassé quelque chose, sans solliciter Ghislain.

**Étapes** :
1. `.github/workflows/ci.yml` sur `windows-latest` :
   - job **test** : `pip install -r requirements.txt` + `pytest tests/ -v` ;
   - job **build** : `build.bat` (adapté CI), puis `dist/Ghisdiag.exe --selftest`,
     et publication de l'exe en artefact (pratique pour la validation atelier :
     Ghislain télécharge l'artefact de la PR, pas besoin de builder localement) ;
   - job **lint** léger : `python -m compileall .` + `ruff check` (config minimale,
     pas de guerre de style).
2. Badge CI dans le README.
3. Règle de process : une PR ne se merge que CI verte + validation atelier si le
   chantier touche capteurs/bench/collecte matérielle.

**Critères d'acceptation** : CI verte sur `main` ; un commit qui casse un test ou
le build fait échouer la PR ; l'exe de PR est téléchargeable en artefact.

---

## Chantier A5 — Processus de chantier standardisé (le « mode opératoire » des IA)

**Priorité : 2 (léger, en parallèle de A2).**

**Objectif** : généraliser ce qui a marché sur le bench GPU pour que chaque
évolution suive le même rail, quelle que soit l'instance qui travaille.

**Étapes** :
1. Créer `docs/templates/PROGRESS_TEMPLATE.md` calqué sur
   [GPU_BENCH_PROGRESS.md](GPU_BENCH_PROGRESS.md) : Objectif, Décisions
   verrouillées (tableau décision/pourquoi), État de l'existant réutilisable,
   Pièges identifiés, Jalons M0→Mn avec critères, **Checklist de validation
   atelier**, Journal de session.
2. Règles de process (à inscrire dans `CLAUDE.md`) :
   - Un chantier = un fichier `<CHANTIER>_PROGRESS.md` + une branche + une PR.
   - Les **décisions verrouillées** ne se rouvrent pas sans l'accord de Ghislain.
   - Chaque session se termine par la mise à jour du journal du chantier.
   - Le hand-off vers l'atelier est un livrable : l'IA rédige la checklist de
     validation (étapes concrètes, résultats attendus, cases à cocher) ; Ghislain
     la remplit et la recolle dans le fichier de progression — c'est l'interface
     homme/machine du projet.
3. `docs/DECISIONS.md` : registre des décisions d'architecture transverses
   (une ligne de contexte, la décision, la raison), alimenté en fin de chantier —
   évite qu'une future IA « améliore » un choix fait exprès (ex. : pas de SDK IA,
   pas de matplotlib, charge GPU en D3D11 pur).

**Critères d'acceptation** : template en place ; le premier chantier de la
Partie B l'utilise de bout en bout ; DECISIONS.md initialisé avec les décisions
déjà connues (rétro-remplissage depuis les notes de release et GPU_BENCH_PROGRESS).

---

## Chantier A6 — Skills Claude Code du dépôt

**Priorité : 5 (confort, une fois A1–A5 en place).**

**Objectif** : encapsuler les procédures répétitives en skills invocables
(`.claude/skills/`), pour fiabiliser les opérations sensibles.

Skills à créer (un dossier chacun, avec `SKILL.md`) :
1. **`release`** — déroule la procédure complète : bump de version (fichiers à
   toucher : `version_info.txt`, README badges, CHANGELOG, RELEASE_NOTES_vX.md,
   ROADMAP), build, SHA-256, tag, release GitHub — en s'appuyant sur
   `finalize_release.ps1`. La procédure existe, elle est aujourd'hui dans la tête
   de l'historique git.
2. **`nouveau-collecteur`** — guide la création d'un collecteur : squelette PS1
   avec Safe-Get, branchement dans `orchestrator.py`, section rapport, règle
   d'alerte + fixture + test, entrée dans la notice.
3. **`chantier`** — instancie le template de A5, crée la branche, initialise le
   fichier de progression.
4. **`validation-atelier`** — génère la checklist de hand-off du chantier courant.

**Critères d'acceptation** : une release complète réalisée via le skill `release`
sans étape oubliée ; un collecteur de la Partie B créé via `nouveau-collecteur`.

---

# PARTIE B — Diagnostic v2 : le carnet de bord de la machine

**But** : faire passer la fonction diagnostic de « inventaire exhaustif + alertes »
à un **carnet de bord de la machine** : verdict hiérarchisé sur les
ralentissements, **enquête forensique sur les instabilités et les arrêts
suspects**, chronologie des événements marquants, mémoire des interventions du
technicien — le tout dans un format **doublement lisible** : par le tech (HTML)
et par une IA (JSON versionné et documenté).

**Les trois axes du Diagnostic v2** :
1. **Ralentissements** — qu'est-ce qui freine cette machine ? (scoring, résumé
   exécutif, boot par phase)
2. **Instabilités & arrêts suspects** — pourquoi cette machine plante-t-elle ou
   s'éteint-elle ? BSOD, arrêts inattendus (coupure ? surchauffe ? bouton ?),
   crashs d'applications, erreurs matérielles — avec **reconstitution de ce qui
   s'est passé autour de chaque incident**.
3. **Mémoire & trajectoire** — qu'est-ce qui a déjà été fait sur cette machine,
   et est-ce que ça va mieux ? Historique des diagnostics, des benchs, des
   interventions notées par le tech.

Ordre conseillé : **B1 → B2 → B3 → B4**, puis B5–B8 en couches au-dessus.
Chaque chantier suit le processus A5 (fichier de progression, décisions
verrouillées, checklist atelier).

---

## Chantier B1 — Moteur de scoring & résumé exécutif « Ce qui ralentit ce PC »

**Le besoin** : le technicien (et le client) veut la réponse à UNE question :
*qu'est-ce qui cloche, par ordre d'importance ?* — en tête de rapport, en 30 s
de lecture.

**Étapes** :
1. Créer `report/scoring.py` : chaque alerte existante de `report/generator.py`
   reçoit un objet `Finding` normalisé : `{id stable, domaine, sévérité (critique/
   grave/moyen/faible), preuve (donnée mesurée + seuil), impact (perf/stabilité/
   sécurité/matériel), action recommandée}`.
   Les règles restent **déclaratives** (comme aujourd'hui) — le scoring est une
   couche au-dessus, pas une réécriture. L'`id` stable (ex. `disk.smart.wear_high`)
   est essentiel : c'est lui qui permettra le suivi dans le temps (B4) et la
   lecture machine (B7).
2. **Score de santé par domaine** (0–100) : Performance, **Stabilité**, Stockage,
   Sécurité, Thermique. Barème simple et documenté (pondération par sévérité),
   assumé comme indicatif — pas de fausse précision.
3. **Résumé exécutif** en tête de HTML : les 3 problèmes prioritaires avec preuve
   et action, puis la jauge par domaine. S'il n'y a rien : le dire clairement
   (« RAS — machine saine »), c'est aussi un verdict vendeur pour l'atelier.
4. Le JSON du rapport embarque `findings[]` et `scores{}` → socle de B4 et B7.

**Critères d'acceptation** : sur le corpus A2, les top 3 sont pertinents et
stables (testés par fixture) ; une machine saine affiche « RAS » ; aucun nouveau
faux positif (les règles n'ont pas changé, seule la présentation).

---

## Chantier B2 — Forensique des instabilités & arrêts suspects ⭐ *chantier phare*

**Le besoin** : « le PC s'éteint tout seul » / « il freeze » / « écran bleu de
temps en temps » — les pannes les plus difficiles à diagnostiquer en atelier,
celles où le technicien passe des heures dans l'Observateur d'événements. Ghisdiag
doit mener cette enquête **automatiquement** et rendre un verdict argumenté :
*quel type d'arrêt, quelle cause probable, quel composant suspecter.*

Aujourd'hui le diagnostic **compte** les BSOD/WHEA (niveau 3, v1.3.0). Demain il
doit les **expliquer**.

**Étapes** :

1. **Classification de chaque arrêt anormal** (`collectors/shutdown_forensics.ps1`) —
   pour chaque événement Kernel-Power 41 / EventLog 6008 des 90 derniers jours,
   croiser les indices pour classer l'arrêt :
   - `BugcheckCode ≠ 0` → **BSOD** (rattacher au dump correspondant, cf. étape 2) ;
   - `PowerButtonTimestamp ≠ 0` → **appui long sur le bouton** (souvent un freeze :
     signal fort d'instabilité, pas un incident électrique !) ;
   - les deux à zéro → **perte d'alimentation brutale** : coupure secteur, bloc
     d'alim défaillant, ou **arrêt de protection thermique** (croiser avec les
     événements ACPI/thermal et — atout unique de Ghisdiag — les sessions du
     bench thermique de la machine) ;
   - arrêt propre mais non sollicité → Windows Update / batterie vide (laptop).
   - Sortie : liste datée `abnormal_shutdowns[]` avec type, indices, confiance.

2. **Autopsie des BSOD** (`collectors/crash_dumps.py`, Python pur) — parser
   l'en-tête des dumps de `C:\Windows\Minidump` et `MEMORY.DMP` (signature
   `PAGEDU64/PAGEDUMP` : le **BugCheckCode et ses 4 paramètres** sont à offset
   fixe, lisibles sans symboles ni WinDbg — fidèle à l'invariant « pas de binaire
   ajouté »). Puis :
   - table de connaissance embarquée `report/bugcheck_kb.py` : code → nom,
     famille de cause (RAM / driver / stockage / surchauffe / alimentation),
     signification des paramètres pour les codes majeurs (0x124 WHEA matériel,
     0x50/0x1A mémoire, 0x116/0x117 TDR vidéo, 0xF4/0x7A stockage, 0x133 DPC…),
     et **geste de vérification atelier** associé (memtest, réassise barrettes,
     déplacement du dump, MAJ pilote GPU nommé…) ;
   - si le nom du module fautif figure dans l'événement BugCheck 1001 ou le
     minidump, l'extraire et le relier à l'inventaire des pilotes (B5.2).

3. **Erreurs matérielles WHEA détaillées** — ne plus seulement compter : extraire
   du XML de l'événement le composant en cause (CPU cache/bus, banque mémoire,
   port PCIe), l'APIC ID / numéro de banque, et agréger : *« 14 erreurs WHEA,
   toutes sur le même cœur CPU »* est un verdict ; « 14 erreurs WHEA » est un
   symptôme.

4. **Crashs d'applications** (`collectors/app_crashes.ps1`) — Event 1000/1002
   (Application Error / Hang) + rapports WER : top des applications qui plantent,
   **module fautif** (un même `xxx.dll` qui revient dans des crashs d'applis
   différentes = piste système : runtime, pilote graphique, RAM), fréquence.
   Inclure les LiveKernelEvents (code 141/117 : le GPU a planté sans BSOD).

5. **Indice de stabilité Windows** — `Win32_ReliabilityStabilityMetrics` (le
   graphe de fiabilité de Windows) : tendance sur 30 jours, gratuite et déjà
   calculée par l'OS ; sert de toile de fond au score Stabilité de B1.

6. **Verdict stabilité** dans le rapport : section « 🧯 Instabilités » avec, par
   incident ou groupe d'incidents : type, date(s), cause probable, **preuves**,
   confiance, et le geste atelier recommandé. Les findings alimentent le score
   Stabilité (B1) et la chronologie (B3).

**Garde-fous** : un incident isolé vieux de 80 jours n'est pas une alerte rouge ;
la récurrence et la récence pondèrent la sévérité. Toujours distinguer « cause
identifiée » / « cause probable » / « indéterminé — gestes de vérification
proposés ». L'invariant zéro-invention s'applique doublement ici.

**Critères d'acceptation** : fixtures réelles de l'atelier pour chaque type
d'arrêt (BSOD avec minidump, bouton forcé, coupure) ; le parseur de dump lit
correctement code + paramètres sur ≥ 3 dumps réels ; la classification 41/6008
est testée sur fixtures ; validation atelier sur une machine à panne connue
(le verdict Ghisdiag doit correspondre au diagnostic manuel du tech).

---

## Chantier B3 — Chronologie unifiée : « que s'est-il passé autour de l'incident ? »

**Le besoin** : la question réflexe du tech devant un plantage : *« qu'est-ce qui
a changé juste avant ? »*. Aujourd'hui il faut fouiller 4 journaux à la main.

**Étapes** :
1. `report/timeline.py` : fusionner en une **chronologie unique datée** les
   événements marquants déjà collectés ou faciles à collecter :
   - incidents (BSOD, arrêts anormaux, WHEA, crashs applis — B2) ;
   - **changements** : installation/MAJ de pilotes (journal `Setup` +
     PnP), Windows Update installés (avec KB), logiciels installés/désinstallés,
     changements de matériel détectés ;
   - erreurs disque/NTFS, services tombés en échec ;
   - diagnostics et benchs Ghisdiag précédents, interventions notées (B4).
2. **Corrélation temporelle automatique** : pour chaque incident, lister ce qui a
   changé dans les N jours précédents → *« les 3 BSOD 0x116 ont commencé 2 jours
   après la mise à jour du pilote NVIDIA 566.14 »*. C'est la règle d'or du
   dépannage, automatisée. Formulée en cause **probable**, avec les dates comme
   preuve.
3. Rendu HTML : frise verticale filtrable (incidents / changements / interventions),
   les corrélations mises en évidence. Rendu JSON : `timeline[]` d'événements
   typés + `temporal_correlations[]`.

**Critères d'acceptation** : sur une fixture « BSOD après MAJ pilote » (à
constituer en atelier), la corrélation sort automatiquement ; les événements de
routine ne polluent pas la frise (seuils de signifiance testés) ; la frise reste
lisible sur une machine chargée (agrégation des répétitions).

---

## Chantier B4 — Carnet de bord machine : mémoire persistante & interventions

**Le besoin** : l'atelier revoit les mêmes machines. Le carnet de bord est le
**dossier patient** de chaque PC : tout ce que Ghisdiag a mesuré et tout ce que
le tech a fait, en un seul endroit — consultable d'un coup d'œil et exportable
pour une IA.

**Étapes** :
1. **Identité machine stable** : empreinte à partir du numéro de série carte
   mère/BIOS (déjà collecté par `system_info.ps1`) — robuste au renommage et à la
   réinstallation de Windows.
2. **Dossier machine** : `Documents\Ghisdiag_Reports\dossiers\<empreinte>\dossier.json` —
   identité matérielle, liste des diagnostics (avec leurs `findings[]` et scores),
   sessions de bench thermique CPU/GPU, incidents B2, **interventions**.
3. **Journal d'interventions saisi par le tech** : petit formulaire dans l'UI
   (« ✍️ Noter une intervention ») : date auto, type (nettoyage, pâte thermique,
   remplacement disque/RAM/alim, réinstallation, MAJ pilote…), commentaire libre.
   C'est la moitié « carnet » du carnet de bord — et le chaînon manquant pour
   les corrélations : *« plus aucun BSOD depuis le remplacement de la RAM le 12/03 »*.
4. **Vue « Dossier machine » dans l'UI** : trajectoire des scores, frise B3
   inter-diagnostics, interventions, verdicts de bench — et **diff automatique**
   avec le diagnostic précédent : problèmes résolus (✅ — la preuve du travail du
   technicien), nouveaux (🔴), persistants (⚠️).
5. **Export dossier** : un JSON autoporteur + un HTML imprimable. Le JSON est
   l'entrée idéale d'une analyse IA (B7) et peut être copié sur clé USB pour
   suivre la machine.
6. Garde-fous : ne comparer que des rapports au schéma compatible ; afficher
   l'écart de temps ; les dossiers sont locaux (aucun envoi réseau — invariant
   vie privée).

**Critères d'acceptation** : deux diagnostics de la même machine → détection
automatique + section évolution ; une intervention saisie apparaît dans la frise
et le diff ; fixtures « même machine à 3 mois d'écart » dans le corpus ; le
dossier JSON se valide contre le schéma B7.

---

## Chantier B5 — Nouveaux collecteurs de diagnostic

Chacun suit le skill `nouveau-collecteur` (A6) : PS1 Safe-Get + règle d'alerte
+ fixture + test. Par ordre de valeur atelier :

1. **Boot par phase** (`collectors/boot_trace.ps1`) — Event ID 100–110 du journal
   `Diagnostics-Performance` : durée MainPath, dégradation par driver/service,
   top des coupables. Alerte au-delà de seuils justifiés (cohérents avec la règle
   60 s existante). *C'est la ligne v1.8.0 de la roadmap.*
2. **Pilotes obsolètes / non signés** (`collectors/drivers_audit.ps1`) — inventaire
   pilotes avec date/signature ; alerte sur non-signé et sur les familles critiques
   très anciennes (GPU, chipset, stockage, réseau). Indiquer la **source de mise à
   jour**. Seuil prudent (un vieux pilote qui marche n'est pas une panne). Sert
   aussi de référentiel aux modules fautifs de B2 et aux corrélations de B3.
3. **Batterie** (`collectors/battery.ps1`, laptops) — `powercfg /batteryreport`
   parsé : usure (design vs full charge), cycles. Alerte usure > 40 %. Très
   vendeur en atelier (devis remplacement chiffré). Un laptop qui s'éteint
   brutalement + batterie usée = classification B2 « batterie » directe.
4. **Mémoire RAM** — résultats du Diagnostic mémoire Windows s'il a tourné
   (journal `MemoryDiagnostics-Results`), configuration des barrettes (canaux,
   vitesses dépareillées) ; proposé en geste de vérification par B2 quand la
   famille de cause est « RAM ».
5. **Santé Windows Update** — échecs répétés d'installation, redémarrage en
   attente depuis > 7 jours, version de Windows en fin de support.
6. **Réseau approfondi** — latence/perte vers passerelle et 2 cibles publiques ;
   distinguer « problème local » de « problème FAI » (grand classique du faux
   diagnostic client).

**Critères d'acceptation** (par collecteur) : fixture réelle + test ; temps de
collecte < 10 s (le diagnostic total doit rester ≈ 20–30 s, collecte parallèle) ;
zéro alerte sur les fixtures de machines saines.

---

## Chantier B6 — Corrélation locale : des causes, pas des symptômes

**Le besoin** : le rapport liste des symptômes qui ont souvent une cause commune.
L'audit IA fait déjà ces liens — les plus sûrs doivent marcher **offline**.

**Étapes** :
1. `report/correlations.py` : règles de causalité déclaratives, chacune avec
   conditions (présence de findings), conclusion, et niveau de confiance affiché.
   Règles initiales (chacune validée sur cas réel avant activation) :
   - erreurs disque + SMART dégradé + boot lent → *disque en fin de vie* ;
   - BSOD 0x124/WHEA récurrents + throttling au bench → *suspicion
     CPU/refroidissement* — proposer un bench thermique si aucun n'existe ;
   - arrêts « perte d'alimentation » (B2) sans événement thermique + desktop →
     *suspicion bloc d'alimentation* ;
   - crashs multi-applications sur le même module + erreurs WHEA mémoire →
     *suspicion RAM* — proposer memtest ;
   - BSOD 0x116 + pilote GPU récemment mis à jour (B3) → *pilote vidéo en cause
     nommé, rollback proposé* ;
   - RAM saturée au repos + N processus lourds au démarrage → *démarrage surchargé*.
2. Dans le résumé (B1), une cause racine **remplace** ses symptômes dans le top 3
   (les symptômes restent dans le corps du rapport, rattachés à la cause).
3. Chaque corrélation est formulée en « cause probable » avec sa preuve — jamais
   en certitude. Le garde-fou anti-invention s'applique tel quel.

**Critères d'acceptation** : fixtures multi-symptômes dans le corpus ; les règles
ne se déclenchent jamais sur les machines saines ; sortie JSON `root_causes[]`.

---

## Chantier B7 — Le format IA : schéma documenté & audit incrémental

**Le besoin** : « déchiffrable par une IA » ne se décrète pas — ça se **spécifie**.
N'importe quelle IA (pas seulement celles configurées dans l'app) doit pouvoir
avaler un dossier machine et raisonner dessus sans deviner le format.

**Étapes** :
1. **Schéma versionné** : `docs/SCHEMA_DIAGNOSTIC.md` + `schema_version` dans
   chaque JSON produit (rapport, dossier machine, session de bench). Le document
   décrit chaque champ, les énumérations (sévérités, types d'arrêt, familles de
   cause), la sémantique des `id` de findings, et des exemples. Règle : tout
   champ ajouté = schéma mis à jour dans la même PR (test A2 qui valide les
   fixtures contre le schéma).
2. **Conventions IA-first** dans les JSON : identifiants stables plutôt que
   libellés, preuves structurées (`{metric, value, threshold, unit, source}`),
   dates ISO 8601, confiance explicite (`confirmed/probable/hypothesis`),
   verdicts jamais implicites. Le HTML est une *vue* de ce JSON, pas l'inverse.
3. **Audit IA incrémental** (`ai_analyzer.py`) : le payload devient
   findings + scores + root_causes + timeline + diff du carnet de bord — le
   prompt demande à l'IA de **valider/compléter le pré-diagnostic local** au lieu
   de repartir de zéro, et de commenter l'évolution (« X résolu depuis le … ;
   Y persiste — escalader »). Conserver la règle d'or : preuve par problème,
   droit de dire « rien à signaler ».
4. **Bouton « Copier le dossier pour une IA »** : exporte le dossier machine JSON
   + un prompt d'accompagnement prêt à coller dans n'importe quel chat IA — pour
   le tech qui veut un second avis sans configurer de clé API.

**Critères d'acceptation** : le schéma documente 100 % des champs des fixtures
(test automatique) ; test « IA froide » : une instance de Claude sans contexte
Ghisdiag reçoit un dossier exporté et doit restituer correctement l'état de la
machine — c'est le critère ultime du « déchiffrable par une IA ».

---

## Chantier B8 — Rapport client vulgarisé (opportuniste)

Vue « client » du rapport (déjà en « Plus tard » dans la roadmap) : le résumé B1,
le verdict stabilité B2 et l'évolution B4 réécrits sans jargon, imprimables en
1 page, avec le verdict et le devis conseillé. À faire une fois B1–B4 stabilisés —
c'est surtout du template HTML, faible risque.

---

## 🗺️ Séquencement global recommandé

| Ordre | Chantier | Dépend de | Cible release | Validation atelier ? |
|---|---|---|---|---|
| 1 | A1 CLAUDE.md | — | hors release | non |
| 2 | A2 Harnais de tests + corpus | A1 | hors release | dump des fixtures |
| 3 | A5 Process de chantier + DECISIONS | A1 | hors release | non |
| 4 | A4 CI Windows | A2 | hors release | non |
| 5 | B1 Scoring + résumé exécutif | A2 | **v1.8.0** | oui (lisibilité rapport) |
| 6 | B5.1 Boot par phase + B5.2 Pilotes | A2 | **v1.8.0** | oui |
| 7 | A3 Découpage main.py | A2 | hors release | rapide (non-régression) |
| 8 | B2 Forensique instabilités ⭐ | A2, B1 | **v1.9.0** | oui (machines à panne connue) |
| 9 | B3 Chronologie unifiée | B2 | **v1.9.0** | oui |
| 10 | B5.3–B5.6 Batterie, RAM, WU, réseau | A2 | v1.9.0 | oui |
| 11 | A6 Skills du dépôt | A5 | hors release | non |
| 12 | B4 Carnet de bord + interventions | B1, B3 | **v2.0.0** | oui (2 passages réels) |
| 13 | B6 Corrélations locales | B2, B3, B5 | **v2.0.0** | oui (cas réels) |
| 14 | B7 Schéma IA + audit incrémental | B4, B6 | v2.0.0 | test « IA froide » |
| 15 | B8 Rapport client | B1, B2, B4 | opportuniste | oui |

Lecture d'ensemble : **v1.8.0** rend le rapport parlant (ralentissements),
**v1.9.0** en fait un enquêteur (instabilités & arrêts suspects), **v2.0.0** en
fait un carnet de bord à mémoire, lisible par n'importe quelle IA. Les chantiers
A s'intercalent : A2 avant tout chantier B (on ne construit pas le Diagnostic v2
sans filet), A3 dès que possible mais jamais en même temps qu'un chantier B qui
touche l'UI.

---

## 📓 Journal du plan

> Chaque session IA qui ouvre ou clôt un chantier de ce plan ajoute une ligne ici
> (date, chantier, état, lien vers le fichier de progression).

- **2026-07-18** — Plan rédigé (état du projet : v1.7.0 publiée, chantier GPU clos).
  Aucun chantier ouvert.
- **2026-07-18** — Partie B renforcée sur demande de Ghislain : axe « instabilités
  & arrêts suspects » (B2 forensique, B3 chronologie), carnet de bord machine avec
  interventions (B4), schéma JSON IA-first (B7).
