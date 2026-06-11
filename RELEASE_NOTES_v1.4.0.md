# PlanetDiag v1.4.0 — Notes de Release

**Date de sortie :** 2026-06-11  
**Version précédente :** 1.3.0

---

> Release **confort & intelligence** : une interface entièrement redessinée —
> moderne, reposante, lisible — et un audit IA qui creuse vraiment :
> corrélations entre les données, cause racine, niveau de confiance,
> et un état des lieux complet même quand le poste va bien.

---

## 🎨 Refonte graphique — thème Catppuccin Mocha unifié

L'application abandonne son thème néon « Ghost Protocol » (cyan électrique sur
noir profond) pour **Catppuccin Mocha**, la palette déjà utilisée par le rapport
HTML. L'app, le rapport diagnostic et le rapport IA partagent désormais la même
identité visuelle.

- **Lisibilité d'abord** : texte principal à contraste AAA, couleurs pastel
  reposantes, plus aucun texte gris-sur-gris illisible
- **Barre de titre Windows sombre** — fini le bandeau blanc qui jurait avec le thème
- **Typographie revue** : Segoe UI pour l'interface, Consolas réservé aux données
  et aux journaux ; les plus petites tailles remontées pour rester lisibles
- **Chaque détail thémé** : scrollbars sombres (18 converties), séparateurs
  discrets, liste déroulante des comptes, boutons pastel avec états de survol
  cohérents, suppression des liserés de focus blancs autour des listes

---

## 🤖 Analyse IA Mistral — audit plus profond, toujours honnête

Le prompt v1.3.0 avait appris à l'IA à ne plus crier au loup. La v1.4.0 lui
apprend à **creuser** — sans rien perdre de cette rigueur :

- **Corrélations obligatoires** : l'IA croise les sections entre elles
  (événement disque ↔ santé SMART, crash ↔ driver, boot lent ↔ programmes au
  démarrage) et le dit explicitement — y compris quand l'absence de corrélation
  disculpe un composant
- **Motifs temporels** : un événement répété en rafale ou à chaque démarrage
  n'a pas le même sens qu'une occurrence isolée — compte exact, période et motif
- **Cause racine** : chaîne causale complète exigée, du déclencheur au symptôme
- **Niveau de confiance** (Élevée/Moyenne/Faible) par diagnostic, avec hypothèse
  alternative et donnée manquante quand l'IA n'est pas sûre
- **Audit enrichi : 10 sections** au lieu de 7 — fiche d'identité du poste,
  revue domaine par domaine (chiffrée, y compris les domaines sains), points de
  surveillance avec seuil de déclenchement, matériel étendu à la projection
  durée de vie/usure (heures de fonctionnement, wear level)
- **Toujours zéro problème inventé** : plus de détails ne veut jamais dire plus
  d'alertes — la richesse est dans le descriptif et les explications

---

## ✅ Vérification Pré-Release

- ✅ Refonte UI validée visuellement sur les 4 onglets (captures + vérification pixel des couleurs)
- ✅ `main.py`, `mistral_analyzer.py`, `mistral_report.py` compilent
- ✅ Application lancée en réel après chaque lot de modifications (aucune erreur)
- ✅ Versions synchronisées (orchestrator, generator, version_info, README, mistral_report)
- ✅ Format de sortie IA compatible avec le rendu du rapport (tableaux markdown interdits)

---

## 🚀 À Savoir Avant le Déploiement

1. **Aucune nouvelle dépendance Python.**
2. **Aucun changement de comportement des collecteurs** — release UI + prompt uniquement.
3. La barre de titre sombre nécessite Windows 10 20H1+ (sans effet ailleurs).

---

## 📝 Modifications

```
feat(ui): refonte graphique — thème Catppuccin Mocha unifié
feat(mistral): prompt enrichi — audit plus profond sans perdre la rigueur
release: bump version 1.4.0 (orchestrator, generator, version_info, README, mistral_report)
```

---

## ⬇️ Téléchargement

- **Exe** : `PlanetDiag.exe`
- **Sha256** : [à remplir après le build]
- **Taille** : [à remplir après le build]
