# Ghisdiag v1.6.5-beta.2 — Notes de Release (pré-release de test)

**Date de sortie :** 2026-06-28
**Version précédente :** 1.6.5-beta.1 (remplacée)
**Statut :** 🧪 **beta** — pour tests sur parc varié. La **1.6.4** reste la version stable.

---

> Correctifs de la **beta.1** après tes premiers tests : la température CPU
> mettait beaucoup de temps à apparaître et se rafraîchissait lentement. C'est
> réglé. **Cette beta.2 remplace la beta.1** — installe celle-ci.

---

## ⚡ Ce qui change depuis la beta.1

- **Température CPU fluide** : le moniteur temps réel rouvrait LibreHardwareMonitor
  (et rechargeait toutes les DLL) à chaque rafraîchissement, et seulement toutes
  les 10 s. Il ouvre maintenant les capteurs **une seule fois** (flux persistant
  avec garde anti-blocage) et affiche la température CPU **en continu (~2 s)**.
- **Repli ACPI rétabli** : sur une machine sans driver PawnIO, la température CPU
  (zone thermique ACPI) réapparaît, même quand un GPU/disque est détecté.

*(Rappel du contenu de la beta : robustesse capteurs anti-freeze, backend LHM
remplaçable, GPU NVML + disques smartctl, mapping température AMD Zen 5, et la
section « Capteurs » du rapport.)*

---

## 🧪 Ce qu'on aimerait que tu testes

1. Lance l'outil **en administrateur** (l'exe le demande automatiquement).
2. Ouvre le **moniteur temps réel** : la température CPU apparaît-elle vite
   (~quelques secondes) et se rafraîchit-elle de façon fluide ?
3. Génère un **rapport** et regarde la section **🌡 Capteurs**.
4. Lance un **bench thermique** court (2 min) : démarre-t-il normalement ?

Modèle de CPU + résultat = retour utile. 🙏

---

## 📦 Installation

1. Télécharge `Ghisdiag.exe` ci-dessous.
2. Double-clique et accepte les droits administrateur.
3. C'est parti !

**Prérequis :** Windows 10/11. Aucune dépendance à installer (tout est embarqué dans l'exe).

- **Sha256** : `3d6235c67b2a322c5ed80abe721d3c0840068c140858f665349908fc728d3b32`
- **Taille** : 23.8 MB
