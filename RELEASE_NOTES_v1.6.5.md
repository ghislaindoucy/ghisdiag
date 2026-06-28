# Ghisdiag v1.6.5 — Notes de Release

**Date de sortie :** 2026-06-28
**Version précédente :** 1.6.4

---

> Cette version fiabilise le **suivi de température** et le **bench thermique** sur
> n'importe quelle machine, et ajoute un vrai **test de stabilité (charge AVX)**.
> Validée sur parc réel (Intel Coffee Lake, AMD Ryzen Zen 5).

---

## 🌡️ Capteurs fiables sur tout-terrain

- **Température CPU sur n'importe quel CPU** : protection anti-blocage (un backend
  capteur figé est détecté et arrêté au lieu de geler l'appli), backend
  LibreHardwareMonitor remplaçable sans recompiler, **GPU NVIDIA via NVML** et
  **disques via smartctl** en mode utilisateur.
- **AMD Ryzen récents (Zen 5)** : mapping de température (Tctl/Tdie) corrigé.
- **Moniteur temps réel fluide** : la température CPU se rafraîchit en continu
  (plus de longue latence au démarrage).
- **On sait pourquoi quand ça manque** : le moniteur indique la cause d'une
  température CPU absente (driver PawnIO manquant, application non élevée…), et le
  rapport HTML gagne une section **« Capteurs »**.

## 🔥 Bench thermique : nettoyage de pâte ET test de stabilité

- **Mode « Stabilité (AVX max) »** : une charge AVX qui sollicite le CPU comme un
  torture-test, pour vérifier qu'une machine tient à pleine charge. (Repli
  automatique sur la charge classique si besoin.)
- Mesures **fidèles** : la charge s'arrête net à la fin du test, et le récapitulatif
  distingue désormais le **throttling thermique** (vrai souci de refroidissement)
  de la **limite de puissance (PL1/TDP)** — qui explique pourquoi la température
  plafonne sans que ce soit un défaut.

## 🐛 Correctif

- La version affichée dans le rapport HTML suit de nouveau la version réelle.

---

## 📦 Installation

1. Télécharge `Ghisdiag.exe` ci-dessous.
2. Double-clique et accepte les droits administrateur.
3. C'est parti !

**Prérequis :** Windows 10/11. Aucune dépendance à installer (tout est embarqué dans l'exe).

- **Sha256** : `08f045b9869ee905c1d16c32e6f51ff37bdb3a0bd978219a2a7ceaabbf283016`
- **Taille** : 33.8 MB
