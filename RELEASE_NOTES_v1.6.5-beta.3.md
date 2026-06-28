# Ghisdiag v1.6.5-beta.3 — Notes de Release (pré-release de test)

**Date de sortie :** 2026-06-28
**Version précédente :** 1.6.5-beta.2 (remplacée)
**Statut :** 🧪 **beta** — pour tests sur parc varié. La **1.6.4** reste la version stable.

---

> Cette beta.3 ajoute un vrai **test de stabilité (charge AVX)** au bench thermique
> et corrige plusieurs points repérés en test réel. **Elle remplace la beta.2.**

---

## 🔥 Nouveau : test de stabilité (charge AVX max)

Dans le **Bench thermique**, l'**Intensité** propose désormais **« Stabilité (AVX max) »** :
une charge AVX (multiplications matricielles numpy/BLAS) qui pousse le CPU comme un
torture-test (~80 GFLOP/s par cœur, bien plus que la charge précédente). Idéal pour
vérifier qu'une machine reste **stable** à pleine charge. Repli automatique sur la
charge classique si numpy est indisponible.

## 🐛 Corrections du bench

- **La charge ne déborde plus sur le refroidissement** (les processus de calcul
  étaient coupés ~30 s trop tard, ce qui faussait la fin du test et le graphe).
- **Plus de faux « throttling thermique »** : la baisse de fréquence normale de fin
  de turbo Intel (PL2→PL1) n'est plus signalée à tort comme un problème.
- **Nouvel indicateur « limite de puissance (PL1/TDP) »** : explique pourquoi la
  température plafonne à charge soutenue — c'est le CPU qui bride sa puissance par
  conception, **pas** un défaut de refroidissement.

*(Pour rappel depuis les betas précédentes : température CPU fluide dans le moniteur,
robustesse capteurs anti-freeze, GPU NVML + disques smartctl, mapping AMD Zen 5,
section « Capteurs » du rapport.)*

---

## 🧪 Ce qu'on aimerait que tu testes

1. Lance l'outil **en administrateur** (l'exe le demande automatiquement).
2. **Bench thermique** → Intensité **« Stabilité (AVX max) »**, durée **Court (2 min)**.
3. Vérifie : la température monte, la charge **s'arrête net** à la fin (le CPU
   redescend tout de suite), et le récap indique le **throttling thermique** et/ou
   la **limite de puissance** correctement.

Modèle de CPU + résultat (T repos, T max, plateau, ΔT) = retour utile. 🙏

---

## 📦 Installation

1. Télécharge `Ghisdiag.exe` ci-dessous.
2. Double-clique et accepte les droits administrateur.
3. C'est parti !

**Prérequis :** Windows 10/11. Aucune dépendance à installer (tout est embarqué dans l'exe).

- **Sha256** : `51c0508b303f06395d24e0a8b69e1114be06ecddaca5ced912f1d95c299a1160`
- **Taille** : 33.8 MB
