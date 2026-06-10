# PlanetDiag v1.3.0 — Notes de Release

**Date de sortie :** 2026-06-10  
**Version précédente :** 1.2.3

---

> Release **diagnostic** : PlanetDiag voit désormais les **vrais** incidents
> (écrans bleus, erreurs matérielles, disque qui souffre, NTFS corrompu) —
> et arrête de crier au loup sur les faux positifs. L'analyse IA, elle,
> diagnostique sur **preuves** et ne s'invente plus de problèmes.

---

## 🆕 Diagnostic de fiabilité — les logs qui comptent vraiment

PlanetDiag collecte maintenant les journaux Windows qu'un technicien de niveau 3
regarde en premier, qui manquaient jusqu'ici :

| Journal | Ce qu'il révèle | Fenêtre |
|---------|-----------------|---------|
| **Plantages / BSOD** | Écrans bleus (avec le **code BugCheck** `0x…`), redémarrages inattendus, coupures | 14 jours |
| **WHEA (matériel)** | Erreurs CPU / RAM / PCIe, corrigées ou non | 30 jours |
| **Disque** | Erreurs d'entrée/sortie, secteurs défectueux, timeouts contrôleur | 14 jours |
| **NTFS** | Corruption du système de fichiers | 14 jours |
| **Services** | Services qui ne démarrent pas, crashent ou dépassent le délai | 7 jours |

Chaque incident grave remonte dans **Points d'attention**, avec sa sévérité et
la marche à suivre (`chkdsk`, contrôle SMART…). Le rapport HTML gagne une bannière
fiabilité, une carte « Plantages (14j) » et un tableau de détail par journal.

---

## 🛡️ Moins de faux positifs — soyons raisonnables

- **« Démarrage lent » fiabilisé** : l'événement Windows ID 100 est journalisé à
  *chaque* démarrage. L'ancienne version croyait donc tout PC « lent ». Désormais
  l'alerte ne se déclenche qu'au-delà d'un **seuil réel de 60 secondes**.
- **Bug de comptage fantôme corrigé** : un journal vide pouvait être compté comme
  « 1 événement », générant de fausses alertes. Corrigé pour **tous** les modules.
- **Bruit des updaters ignoré** : les échecs à répétition de Google/Edge Update
  (inoffensifs et chroniques) ne déclenchent plus d'alerte « services en échec ».

---

## 🤖 Analyse IA Mistral — précise et honnête

- **Preuve obligatoire** : chaque problème signalé cite la donnée exacte qui le
  prouve (section + ID d'événement ou valeur mesurée).
- **Seuils de référence** fournis à l'IA (RAM < 75 % = normal, boot < 60 s = normal,
  Defender désactivé + antivirus tiers actif = **normal**…) pour qu'elle ne
  transforme plus une valeur saine en problème.
- **Trois niveaux distincts** : CORRECTIF (à réparer) / OPTIMISATION (optionnel) /
  SURVEILLANCE (signal faible). Fini les optimisations déguisées en urgences.
- **Section conditionnelle** : si le poste est sain, l'IA l'écrit clairement
  (« Aucun problème avéré détecté ») au lieu d'inventer pour remplir.
- **Rapport complet sans troncature** : les données partent en JSON compact, donc
  l'IA reçoit l'intégralité du diagnostic même sur une machine très chargée.

---

## ✅ Vérification Pré-Release

- ✅ `events.ps1` parse sans erreur + exécuté en réel (5 nouveaux journaux peuplés, 0 erreur collecteur)
- ✅ `generator.py` et `mistral_analyzer.py` compilent
- ✅ Diagnostic complet via orchestrateur : **8/8 collecteurs OK** en ~17 s
- ✅ Garde-fous testés : démarrage lent (45 s → rien, 75 s → alerte), WHEA corrigé/non corrigé, dédup bruit SCM
- ✅ Payload Mistral compact (~109 k chars) < fenêtre contexte
- ✅ Versions synchronisées (orchestrator, generator, version_info, README, mistral_report)

---

## 🚀 À Savoir Avant le Déploiement

1. **Fenêtres d'analyse élargies** : les incidents graves sont cherchés sur 14-30 jours
   (et non plus seulement 72 h), pour capturer un BSOD ou une panne disque de la semaine.
2. **Droits administrateur** toujours recommandés pour l'accès complet aux journaux.
3. **Aucune nouvelle dépendance Python.**

---

## 📝 Modifications

```
feat(events): logs L3 — crash/BSOD, WHEA, disque, NTFS, services
feat(report): analyse fiabilité + section HTML dédiée
fix(report): seuil démarrage lent 60s (fin du faux positif systématique)
fix(report): correction comptage fantôme des collections vides
fix(report): filtre du bruit des updaters tiers (Google/Edge Update)
feat(mistral): prompt anti-faux-positif (preuve + seuils + niveaux d'action)
perf(mistral): payload JSON compact (rapport complet sans troncature)
```

---

## ⬇️ Téléchargement

- **Exe** : `PlanetDiag.exe`
- **Sha256** : _(à compléter après build)_
- **Taille** : _(à compléter après build)_
