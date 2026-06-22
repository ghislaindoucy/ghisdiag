# Ghisdiag v1.6.4 — Notes de Release

**Date de sortie :** 2026-06-22
**Version précédente :** 1.6.3

---

> Correctif **important** de justesse du diagnostic : suppression d'un faux
> positif « Corruption NTFS » déclenché par un événement de routine signalant
> au contraire un volume **sain**.

---

## 🐛 Correctif

- **Faux positif « Corruption système de fichiers (NTFS) »** — l'événement
  `Microsoft-Windows-Ntfs` **ID 98** (« *Volume X est sain. Aucune action n'est
  nécessaire* », niveau Info) est émis par l'auto-vérification de routine de
  NTFS. Il était à tort inclus dans les événements de corruption, ce qui
  déclenchait une **alerte critique** à chaque vérification (potentiellement
  plusieurs fois par jour).
- Seuls les identifiants réellement liés à une corruption ou un risque sont
  désormais retenus : **55** (structure NTFS corrompue), **57** (échec
  d'écriture du journal de transactions), **137** (gestionnaire transactionnel
  en erreur non récupérable).
- Un système sain affiche maintenant correctement « **Aucune erreur NTFS** ».

---

## 📦 Installation

1. Télécharge `Ghisdiag.exe` ci-dessous.
2. Double-clique et accepte les droits administrateur.
3. C'est parti !

**Prérequis :** Windows 10/11. Aucune dépendance à installer (tout est embarqué dans l'exe).

- **Sha256** : `ca48855cc77b6c53041896394dc2e80f705773d191c75367e3a6c9c93eeb19f6`
- **Taille** : 23.7 MB
