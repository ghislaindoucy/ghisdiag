# Ghisdiag v1.8.2 — Notes de Release

**Date de sortie :** 2026-07-24
**Version précédente :** 1.8.1

---

> **Poser une question à l'IA.** Jusqu'ici, l'analyse IA produisait un audit
> complet mais figé. Cette version ajoute un **champ question optionnel** : en
> plus de l'audit, tu peux joindre une question précise en rapport avec le poste
> (« pourquoi ça rame au démarrage ? », « ce SSD est-il en fin de vie ? ») et
> l'IA y répond en tête de rapport, appuyée sur les données réelles du
> diagnostic.

---

## 🤖 Question libre à l'IA

- **Champ question optionnel** (500 caractères, compteur en direct) dans le
  panneau **Analyse IA** de l'onglet Analyse. Il n'apparaît que si une clé API
  est configurée.
- La réponse arrive dans une section **« Réponse à ta question » placée en tête
  du rapport IA**, avant le résumé exécutif, argumentée sur les données du
  diagnostic (avec commandes exactes quand c'est pertinent). L'audit complet
  habituel suit normalement en dessous.
- La **question posée est rappelée** dans l'en-tête du rapport, pour garder une
  trace de ce qui a été demandé.
- **Garde-fou hors-sujet** : si la question ne concerne pas le poste ni son
  dépannage (recette de cuisine, culture générale, autre machine…), l'IA la
  décline poliment en une phrase et produit quand même l'audit complet.
- **Sans question**, le comportement est strictement identique aux versions
  précédentes — l'audit automatique n'est pas modifié.

## 🔒 Sécurité

- La question est traitée comme une **donnée**, jamais comme une instruction :
  backticks et sauts de ligne retirés, longueur tronquée à 500 caractères. Elle
  ne peut pas détourner le prompt ni casser le formatage du rapport
  (anti-injection).

## 🧹 Interne

- Nouveau `ai_analyzer._build_question_block()` ; paramètre `question` ajouté à
  `_build_user_prompt`, `analyze_diagnostic` et `generate_ai_report` (défaut
  vide → rétro-compatible).

---

## 🩹 Correctif — re-build du 2026-07-24 (version inchangée)

> Si tu as téléchargé l'exécutable avant ce correctif, **re-télécharge-le** :
> même version 1.8.2, mais binaire différent (SHA-256 ci-dessous).

- **Bench thermique, cible GPU bloquée sur « Détection des cartes graphiques en
  cours… réessayez dans quelques secondes »** : le message pouvait rester
  affiché indéfiniment, rendant le bench GPU inaccessible jusqu'au redémarrage
  de l'application. Le bench CPU n'était pas concerné.
- Cause : la détection des cartes graphiques tourne en tâche de fond et publie
  son résultat sur l'interface. Quand elle allait **très vite** — carte NVIDIA
  lue via NVML, ~50 ms — elle pouvait terminer avant que l'interface ne soit
  prête à recevoir le résultat, qui était alors perdu sans trace. Les machines
  sans NVIDIA passaient au travers du problème (détection en 1-3 s via
  LibreHardwareMonitor, donc jamais trop tôt).
- Corrigé sur trois plans : détection lancée **après** l'ouverture de la
  fenêtre, **réessais** si l'interface n'est pas encore prête, et **relance
  automatique** à chaque bascule sur la cible GPU tant qu'aucun résultat n'est
  disponible.
- Couvert par des tests de non-régression (`tests/test_bench_gpu_detect.py`).

---

## 📦 Fichier

- **Ghisdiag.exe** `1.8.2.0`
- Taille : 33.9 MB (35 528 656 octets)
- SHA-256 : `2b09a3078da7c16df3ae9ae714539bc4441eaf46b7b64c8f1bdcdb8f11156c94`

---

## 🔎 Validation

- Vérifié en atelier : question en rapport avec le diagnostic (réponse
  pertinente en tête de rapport) **et** question hors-sujet (refus poli, audit
  complet quand même produit).
