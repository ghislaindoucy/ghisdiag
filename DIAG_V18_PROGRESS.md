# Chantier v1.8.0 — « Diagnostic encore plus parlant »

Suivi de chantier (même format que `GPU_BENCH_PROGRESS.md`). Ouvert le 2026-07-19.

**Objectif** (cf. ROADMAP v1.8.0) : rendre le rapport immédiatement actionnable pour
le technicien ET parlant pour le client, sans collecter plus — mieux exploiter ce
qu'on collecte déjà.

## Milestones

| # | Milestone | État | Notes |
|---|---|---|---|
| M1 | **Résumé exécutif « Ce qui ralentit ce PC »** — top 3 priorisé en tête du rapport HTML | ✅ | Moteur de règles `report/exec_summary.py` (10 règles / 14 freins possibles, scores impact perf), section héro + nav, findings aussi dans le JSON (`executive_summary`) pour l'audit IA. Tests unitaires. |
| M2 | **Pilotes obsolètes / non signés** — détection + source de mise à jour | ✅ | `software.ps1` : signature/classe/présence par driver, listes `unsigned_drivers` + `outdated_drivers` (>5 ans, matériel présent, classes pertinentes, drivers boîte Windows exclus — signer strict `"Microsoft Windows"`, PAS `-match` : WHQL vendeur = "…Hardware Compatibility Publisher"). Rapport : cartes, tableaux, colonne « Où mettre à jour » par classe, alertes avec garde-fou bruit (GPU/réseau, ou ≥3). Validé en réel sur la machine de dev (229 drivers, 0 faux positif inbox). Tests. |
| M3 | **Analyse du boot par phase** — Event ID 100 (MainPath, drivers, services, profil) | ✅ | `events.ps1` : `boot_phases` extrait du payload XML de l'ID 100 (14 champs ms). Rapport : tableau « dernier démarrage phase par phase » (5 familles, barres de part), ligne post-boot (travail en arrière-plan + nb d'applis), piste de diagnostic seulement si boot ≥ 60 s ET phase ≥ 40 % (garde-fou bruit). Rétro-compatible (vieux JSON sans `boot_phases` = pas de bloc). Tests. **Reste : validation atelier sur une machine avec ID 100 réels** (journal vide/inaccessible sur le poste de dev non-admin). |
| M4 | **Historique des diagnostics** — comparer 2 rapports JSON dans le temps | ⬜ | La machine s'améliore ou se dégrade ? Synergie avec le bench thermique. |
| M5 | **Build & release v1.8.0** | ⬜ | Bump, CHANGELOG, RELEASE_NOTES, ROADMAP, exe, release GitHub. |

## Décisions M1

- **Moteur de règles séparé** (`report/exec_summary.py`, fonctions pures sans HTML) :
  testable unitairement, le générateur ne fait que le rendu.
- **Score = impact perf ressenti** (0-100), pas gravité sécurité : le résumé répond à
  « pourquoi ce PC rame », les alertes sécurité restent dans ⚠ Points d'attention.
- **Garde-fous honnêteté** (dans la lignée du projet) :
  - Disque mécanique : verdict fort seulement si c'est le **seul** disque interne
    (sinon Windows est peut-être sur le SSD → constat conditionnel, score réduit).
  - Disques USB exclus de la règle HDD (un disque externe ne ralentit pas Windows).
  - RAM/CPU chargés à l'instant T : formulé comme un constat instantané, avec le
    processus responsable nommé.
- **Top 3 affiché**, les autres freins comptés en une ligne (pas de mur de texte).
- Les findings sont **aussi injectés dans le JSON** (`executive_summary`) → l'audit IA
  et le futur historique (M4) les exploitent sans re-déduire.

## Journal

### Session 1 — 2026-07-19

- Ouverture du chantier, cadrage M1-M5.
- M1 livré : `report/exec_summary.py` + section héro dans `report/generator.py`,
  styles `assets/report.css`, tests `tests/test_exec_summary.py`.
- M2 livré : `collectors/software.ps1` étendu (non signés / anciens), rapport +
  alertes, tests `tests/test_report_drivers.py`. Collecteur exécuté en réel sur la
  machine de dev : total=229, unsigned=0, outdated=2 (lecteur cartes Realtek 2018,
  SATA AHCI Intel 2019) — pertinent, zéro bruit inbox 2006.
- Piège documenté : ne PAS filtrer l'obsolescence sur `signer -match "Microsoft"` —
  tous les drivers WHQL vendeurs sont signés « Microsoft Windows Hardware
  Compatibility Publisher ». Seul le signataire exact « Microsoft Windows »
  désigne un driver boîte.
- M3 livré : `events.ps1` extrait `boot_phases` (ID 100), rapport avec familles de
  phases + piste dominante, tests `tests/test_report_boot_phases.py`. Le journal
  Diagnostics-Performance du poste de dev est vide/inaccessible (non-admin) :
  extraction validée en synthétique, collecteur complet exécuté sans erreur —
  la validation avec de vrais ID 100 se fera en atelier (exe élevé).
