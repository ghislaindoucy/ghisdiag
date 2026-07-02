# Ghisdiag v1.6.6 — Notes de Release

**Date de sortie :** 2026-07-02
**Version précédente :** 1.6.5

---

> Version **correctif** : accessibilité de l'interface sur les **laptops à petit
> écran** et en **mise à l'échelle Windows 125 %/150 %**. Plus aucun bouton ni
> contrôle coupé hors de la fenêtre. Aucune nouvelle fonctionnalité, uniquement
> des correctifs d'affichage — mise à jour recommandée pour les techniciens en
> atelier qui utilisent des portables.

---

## 🐛 Ce qui est corrigé

- **Setup › PC Neuf** : le panneau est désormais **défilable**. Le bouton
  « Ajouter les icônes du bureau » (et le journal en dessous) pouvait être coupé
  hors de l'écran sur un portable à petit écran ou en forte mise à l'échelle —
  d'où son absence apparente signalée à l'installation d'un PC neuf.
- **Bench thermique** : les contrôles du bas (« Comparer avant/après » et la
  liste des sessions) sont **réservés en priorité**. Sur petit écran, c'est le
  graphe qui rétrécit, plus ces boutons qui disparaissent.
- **Fenêtres Configuration IA, mise à jour winget et attente d'analyse IA** :
  leur taille suit désormais **leur contenu** au lieu d'une taille figée. Elles
  restent entièrement lisibles quelle que soit la mise à l'échelle de l'écran.
- **Fenêtre Licences & mentions légales** : le bouton « Fermer » reste **toujours
  visible**, même fenêtre très rétrécie.

---

## 📦 Installation

1. Télécharge `Ghisdiag.exe` ci-dessous.
2. Double-clique et accepte les droits administrateur.
3. C'est parti !

**Prérequis :** Windows 10/11. Aucune dépendance à installer (tout est embarqué dans l'exe).

- **Sha256** : `6e2556bef9ebb12aaaac3fcc906698d91e49edfebe741e5904d26315fcde8fa2`
- **Taille** : 33.8 MB
