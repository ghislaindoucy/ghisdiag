# Ghisdiag v1.7.0 — Notes de Release

**Date de sortie :** 2026-07-17
**Version précédente :** 1.6.6

---

> Version **majeure** : le bench thermique avant/après s'étend à la **carte
> graphique**. Chauffe reproductible du GPU (tous fabricants, sans rien
> installer), mesures fiables via le pilote NVIDIA, comparaison avant/après et
> rapport client dédiés. Validé en atelier sur RTX 4060, GTX 1060, GT 1030,
> Quadro P2000, AMD APU et Intel iGPU — **aucun plantage ni reset de pilote**.

---

## 🎮 Nouveau : bench thermique GPU

Le même protocole éprouvé que pour le CPU — repos → charge → refroidissement —
appliqué à la carte graphique, pour objectiver un dépoussiérage ou un changement
de pâte/pads thermiques :

- **Cible CPU / GPU** dans l'onglet bench, avec choix de la carte si la machine
  en a plusieurs (« Auto » sélectionne la carte dédiée). Les GPU intégrés sans
  capteur sont refusés avec une explication claire, jamais un test dans le vide.
- **Charge GPU universelle** : compute shader Direct3D 11 — NVIDIA, AMD, Intel,
  sans binaire supplémentaire ni installation. Calibrée pour ne jamais déclencher
  de réinitialisation du pilote (TDR) : 0 incident sur tout le parc de test.
- **Mesures qui disent la vérité** : température, fréquence, puissance et
  **raison de bridage lues directement auprès du pilote NVIDIA (NVML)** — les
  outils génériques peuvent afficher une fréquence figée sous charge. Repli
  automatique sur LibreHardwareMonitor pour AMD/Intel.
- **Sécurité** : arrêt automatique avant le seuil de bridage constructeur de la
  carte (90 °C au plus), ou dès que le pilote confirme un bridage thermique réel.
- **Verdict clair** : throttling **thermique** (vrai souci de refroidissement)
  distingué de la **limite de puissance** (comportement normal de la carte).

## 📊 Comparaison avant / après GPU

- Sélection de 2 sessions GPU → **rapport HTML dédié** : verdict chiffré
  (« −14 °C en charge — intervention efficace »), carte des gains (ΔT, plateau,
  max, retour au calme, **hotspot** — révélateur du contact pâte/pads, chute de
  fréquence, puissance), courbes superposées.
- **Garde-fous honnêteté** : protocole identique ET **même carte** exigés ;
  le ΔT (insensible à la température ambiante) reste la mesure de référence.
- **Liste des sessions filtrée CPU | GPU** : plus de mélange entre les benchs
  des deux familles.

## 🌡️ Capteurs GPU enrichis

- Lecture NVIDIA enrichie (puissance, fréquences, bridage décodé, identité).
- Fréquence / puissance / nom du GPU désormais remontés pour tous les
  fabricants dans le moniteur temps réel.

---

## 📦 Installation

1. Télécharge `Ghisdiag.exe` ci-dessous.
2. Double-clique et accepte les droits administrateur.
3. C'est parti !

**Prérequis :** Windows 10/11. Aucune dépendance à installer (tout est embarqué dans l'exe).

- **Sha256** : `[à remplir après le build]`
- **Taille** : [à remplir après le build]
