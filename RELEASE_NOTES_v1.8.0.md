# Ghisdiag v1.8.0 — Notes de Release

**Date de sortie :** 2026-07-19
**Version précédente :** 1.7.0

---

> **Diagnostic encore plus parlant** : le rapport dit en une seconde **ce qui
> ralentit le PC**, signale les **pilotes obsolètes ou non signés** (et où les
> mettre à jour), décompose un **démarrage lent phase par phase**, et compare
> **deux diagnostics dans le temps** — la machine s'améliore ou se dégrade ?

---

## 🚦 Nouveau : « Ce qui ralentit ce PC »

Le rapport s'ouvre désormais sur le **top 3 des freins de performance**,
priorisés par impact ressenti, chacun avec un constat chiffré et l'action à
proposer au client :

- Windows sur disque mécanique, RAM insuffisante ou saturée, disque plein,
  disque en fin de vie, démarrage lent (avec les applications responsables),
  surchauffe CPU, antivirus multiples, démarrage encombré…
- **Honnête par construction** : si un SSD cohabite avec le disque mécanique,
  le verdict reste prudent ; les mesures prises à l'instant du diagnostic sont
  annoncées comme telles ; un collecteur en échec ne produit jamais de faux
  frein.

## 🔌 Nouveau : pilotes obsolètes / non signés

- **Pilotes non signés** sur du matériel actif : signalés avec le périphérique
  concerné.
- **Pilotes anciens (plus de 5 ans)** sur le matériel qui compte (GPU, réseau,
  audio, stockage) : tableau avec la **source de mise à jour** conseillée
  (site du fabricant du GPU, du constructeur du PC, Windows Update…).
- Les pilotes livrés avec Windows — volontairement datés de 2006 — sont
  exclus : **zéro faux positif** sur un parc réel de 229 pilotes testés.

## ⏱ Nouveau : le démarrage, phase par phase

Quand Windows a mesuré le dernier démarrage, le rapport le décompose :
noyau, **pilotes**, services, **profil**, bureau — avec la part de chaque
phase et le travail en arrière-plan après l'affichage du bureau. Si une phase
domine un démarrage lent, une **piste de diagnostic** est proposée (pilote qui
traîne, service en timeout, profil/GPO lent…).

## 📈 Nouveau : historique des diagnostics

Un bouton **« Historique… »** dans l'onglet Analyse compare deux rapports de
la même machine à deux dates :

- **Freins résolus ✅ / apparus 🆕 / persistants ⏳** — l'effet de votre
  intervention, noir sur blanc.
- **12 chiffres clés** : durée de démarrage, écrans bleus, erreurs matérielles,
  espace disque, pilotes… et **l'usure SMART suivie disque par disque**
  (un disque remplacé n'est pas compté comme une dégradation).
- **Verdict clair** : amélioration / stable / dégradation — pondéré uniquement
  par les éléments durables, jamais par la charge CPU/RAM du moment.
- Fonctionne avec les rapports JSON des **versions précédentes** de Ghisdiag.

---

## 📦 Installation

1. Télécharge `Ghisdiag.exe` ci-dessous.
2. Double-clique et accepte les droits administrateur.
3. C'est parti !

**Prérequis :** Windows 10/11. Aucune dépendance à installer (tout est embarqué dans l'exe).

- **Sha256** : `8af89dca9dfb5178f69f47e1f887b6817298399ed2cd5bf803f109690305067f`
- **Taille** : 33.9 MB
