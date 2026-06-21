# Ghisdiag v1.6.1 — Notes de Release

**Date de sortie :** 2026-06-21
**Version précédente :** 1.6.0

---

> Release de **finitions** : nouveau logo dans l'application, lien de soutien
> « offrez-moi un café », nettoyage des journaux Windows pour repartir d'une base
> de test propre et notice d'utilisation illustrée au format PDF.

---

## 🎨 Interface & branding

- **Logo chat dans l'en-tête** — l'ancienne planète stylisée cède la place au visuel
  chat de l'application (la même icône que la barre de titre et la barre des tâches).
  Le logo est chargé via le moteur d'image natif de Tk (aucune dépendance PIL ajoutée,
  l'exe reste compact) et l'app retombe proprement sur l'ancienne planète si l'asset
  est introuvable.
- **Lien de soutien « ☕ Offrez-moi un café »** — un lien PayPal discret est désormais
  proposé dans l'en-tête de l'application, le README et la notice, pour celles et ceux
  qui souhaitent récompenser le travail.

## 🧹 Maintenance

- **Vider les journaux Windows** — nouvelle action dans l'onglet *Dépannage → Réparation
  système*. Après une réparation, les erreurs et plantages *antérieurs* restent visibles
  dans le diagnostic (un BSOD jusqu'à 14 jours, un démarrage lent jusqu'à 30 jours).
  Cette option efface, journal par journal, les journaux d'événements réellement lus par
  le diagnostic (System, Application, Setup et journaux opérationnels associés) afin de
  valider qu'une réparation a bien réglé le problème, sur une base vierge.

## 📖 Documentation

- **Notice d'utilisation au format PDF** — document illustré couvrant l'ensemble des
  fonctionnalités : les onglets, le bench thermique, l'obtention et la configuration des
  clés API pour les 5 fournisseurs d'IA, l'intérêt de l'analyse IA, le glossaire et la
  section « Vider les journaux Windows ».

---

## 📦 Installation

1. Télécharge `Ghisdiag.exe` ci-dessous.
2. Double-clique et accepte les droits administrateur.
3. C'est parti !

**Prérequis :** Windows 10/11. Aucune dépendance à installer (tout est embarqué dans l'exe).
