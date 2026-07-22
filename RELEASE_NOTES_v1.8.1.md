# Ghisdiag v1.8.1 — Notes de Release

**Date de sortie :** 2026-07-22
**Version précédente :** 1.8.0

---

> **Confort petits écrans.** Sur les portables 14" et les écrans 1080p en mise
> à l'échelle Windows (125/150 %), Windows virtualise la résolution : l'app ne
> « voit » qu'environ 1280×720 pixels logiques. Résultat, le bas de certains
> onglets se retrouvait coupé sous la barre des tâches. Cette version rend
> l'interface entièrement défilable et allège l'en-tête sur les petits écrans.

---

## 🖥️ Interface adaptative

- **Tous les onglets sont désormais défilables.** Les onglets **Analyse** et
  **Bench thermique** rejoignent Dépannage / WiFi / Setup, qui l'étaient déjà.
- **Barre intelligente** : elle n'apparaît que si la fenêtre est trop courte
  pour tout afficher. Sur grand écran, rien ne change — le journal d'activité et
  le graphe du bench s'étirent pour remplir l'espace comme avant.
- **En-tête compact** en dessous de 800 px de hauteur utile : le sous-titre est
  masqué, le logo réduit, les liens (café / GitHub / licences) passent sur une
  seule ligne et les onglets sont resserrés. Environ **100 px rendus au
  contenu** utile.
- **Fenêtre restaurée bornée à l'écran** : en quittant le mode maximisé sur un
  petit écran, la fenêtre ne débordait plus sous la barre des tâches.

## 🐛 Corrections

- **Molette de défilement.** Chaque panneau installait son propre gestionnaire
  global de molette ; la dernière zone construite captait alors la molette de
  toute l'application (faire défiler un onglet pouvait agir sur un autre). Un
  routeur unique dirige désormais la molette vers la zone effectivement
  survolée par le pointeur.

## 🧹 Interne

- Les 6 zones défilantes, jusque-là copiées-collées, sont factorisées en un
  helper unique `_scrollable()`.

---

## 📦 Fichier

- **Ghisdiag.exe** `1.8.1.0`
- Taille : 33.9 MB (35 542 557 octets)
- SHA-256 : `34b89da95165cdf6d24a06c9826d4af492e330d9201c3893efafc3ad18e7b265`

---

## 🔎 Validation

- Vérifié en atelier sur HP Pavilion 14" (14-ce0009nf, i5-8250U, écran 1080p en
  mise à l'échelle) — affichage correct, aucun contenu coupé.
