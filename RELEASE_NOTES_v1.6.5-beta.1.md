# Ghisdiag v1.6.5-beta.1 — Notes de Release (pré-release de test)

**Date de sortie :** 2026-06-27
**Version précédente :** 1.6.4
**Statut :** 🧪 **beta** — pour tests sur parc varié. La **1.6.4** reste la version stable.

---

> Cette beta rassemble le chantier **robustesse des capteurs et du bench
> thermique**. Le but est de la faire tourner sur un maximum de machines
> différentes (Intel récents/anciens, AMD Ryzen, mini-PC) pour confirmer que la
> température CPU remonte — ou, à défaut, que l'outil **dit pourquoi**.

---

## 🌡️ Nouveautés

- **Anti-freeze des capteurs** : un backend figé est détecté et tué (watchdog) au
  lieu de geler l'application ; le bench thermique vérifie que la température CPU
  répond avant de lancer son protocole.
- **Backend LibreHardwareMonitor remplaçable** sans recompiler (dossier `tools`
  override) : on peut déposer une DLL plus récente pour un CPU très récent.
- **GPU NVIDIA (NVML)** et **disques (smartctl)** lus en mode utilisateur, sans
  dépendre de LibreHardwareMonitor — plus tout-terrain.
- **Température AMD** : mapping `Core (Tctl/Tdie)` / `CCDx (Tdie)` ajouté (corrige
  l'absence de température sur Ryzen récents, ex. Zen 5).
- **Santé capteurs visible** : le moniteur indique pourquoi une température CPU
  manque (PawnIO absent, console non élevée, CPU non supporté…) ; nouvelle section
  **« Capteurs »** dans le rapport HTML.

## 🐛 Correctif

- La version affichée dans le rapport HTML (restée à 1.6.0) suit de nouveau la
  version réelle.

---

## 🧪 Ce qu'on aimerait que tu testes

1. Lance l'outil **en administrateur** (l'exe le demande automatiquement).
2. Ouvre le **moniteur temps réel** : la température CPU s'affiche-t-elle ? Sinon,
   quelle **raison** est indiquée à côté de « CPU : N/A » ?
3. Génère un **rapport** et regarde la section **🌡 Capteurs**.
4. Lance un **bench thermique** court (2 min) : démarre-t-il, ou refuse-t-il
   proprement faute de capteurs ?
5. En cas de souci, le détail est dans `diagnose_sensors.py` (sortie à copier).

Modèle de CPU + résultat = retour utile. 🙏

---

## 📦 Installation

1. Télécharge `Ghisdiag.exe` ci-dessous.
2. Double-clique et accepte les droits administrateur.
3. C'est parti !

**Prérequis :** Windows 10/11. Aucune dépendance à installer (tout est embarqué dans l'exe).

- **Sha256** : `548608daa6374889a5c08b4b4b22d49d035a49fbba628e1dabce2c88c5cb3a6c`
- **Taille** : 23.7 MB
