# Ghisdiag v2.0.3 — le bench thermique ne conclut plus sur un test incomplet

Cette version clôture le chantier de fiabilité du bench thermique commencé en
2.0.1. Elle ne corrige pas une panne : elle corrige des **affirmations**. Un
outil de diagnostic qui répond « non » là où il aurait dû répondre « je n'ai pas
pu mesurer » fait douter d'un matériel sain — ou rassure sur un matériel qui
chauffe.

---

## Un test écourté ne dit plus « pas de throttling »

Quand la charge est coupée avant son terme — arrêt d'urgence au seuil de
sécurité, test interrompu — le rapport affichait encore :

> Throttling thermique : **non**

Mesuré en atelier sur un HP Omen Ryzen 9 : la charge s'arrêtait au bout de
**23 secondes sur 300 prévues**. Les quelques fréquences relevées pendant cette
montée en température ne montraient aucune chute — évidemment, le régime établi
n'avait pas commencé. L'outil en concluait l'absence de bridage.

Il répond désormais **indéterminé**, et dit quoi faire :

> ℹ Throttling non mesuré : la charge a été écourtée avant le régime établi —
> sur une simple montée en température, l'absence de chute de fréquence ne
> prouve rien. Il n'est ni confirmé, ni écarté. Refaire un test qui va à son
> terme pour trancher.

Un **oui** reste un oui : une détection sur une fenêtre courte reste une
détection. Et la note distingue enfin les deux causes possibles d'un
indéterminé — fréquences illisibles sur cette machine, ou test trop court.
Annoncer « fréquence non lisible » sur une machine qui remonte parfaitement ses
fréquences aurait remplacé un mensonge par un autre.

## La machine était-elle vraiment au repos ?

La température de repos est le **point zéro de toute la mesure** : le ΔT en
dépend, et une comparaison avant/après compare deux ΔT.

Mesuré en atelier : **16,5 % de charge CPU** pendant une phase censée être au
repos — maintenance Windows juste après un démarrage. Le repos en ressortait
surévalué, donc le ΔT sous-évalué, et rien ne le signalait.

C'est maintenant affiché, avec le chiffre et la marche à suivre. Les valeurs
sont conservées : contrairement au plateau d'une charge écourtée — qui n'a
jamais existé — un repos chargé reste une mesure, le ΔT est un minimum.

En comparaison avant/après, le gain n'est plus chiffré quand **une seule** des
deux sessions est concernée : c'est cette asymétrie qui fabrique un faux gain,
un point de départ décalé d'un côté suffit à inventer des degrés que personne
n'a gagnés. Deux repos également chargés ne bloquent pas.

## Une interruption des capteurs ne coûte plus le test entier

Quand le moteur de capteurs se figeait — observé sur deux machines, dont une
**en fin de bench** — le test s'arrêtait là. Dix minutes déjà écoulées, perdues.

- Le moteur est désormais **relancé automatiquement** ; le test n'est abandonné
  qu'après plusieurs échecs consécutifs.
- Une interruption **pendant la charge** coupe la charge par sécurité — pendant
  ce silence, la surveillance de température est aveugle — mais le
  refroidissement est quand même mesuré, et la charge écourtée est signalée
  comme telle.
- Les interruptions sont **enregistrées dans la session** (moment, phase,
  reprise ou non) et affichées. Le plus long silence du flux est mesuré même
  quand il ne déclenche rien : de quoi voir venir le problème la prochaine fois.

---

## Vos anciennes sessions se corrigent toutes seules

Les sessions déjà enregistrées sont **relues correctement** sans être rejouées :
la requalification se fait à la lecture. Une comparaison avant/après faite l'an
dernier peut donc changer de verdict — c'est voulu, et c'est le bon sens de la
correction.

---

## 📥 Téléchargement

| | |
|---|---|
| **Fichier** | `Ghisdiag.zip` |
| **Taille** | `À_RENSEIGNER` octets |
| **SHA-256** | `À_RENSEIGNER` |

> Ces valeurs portent sur l'archive **compilée par GitHub Actions** à partir du
> tag `v2.0.3` — celle qui est jointe à cette release et qui porte l'attestation
> de provenance.

Vérifier l'intégrité :

```powershell
Get-FileHash Ghisdiag.zip -Algorithm SHA256
```

Vérifier la provenance :

```powershell
gh attestation verify Ghisdiag.zip --repo ghislaindoucy/ghisdiag
```

**Prérequis :** Windows 10/11. Rien d'autre à installer. Décompressez l'archive
et gardez le dossier entier.

---

Le correctif capteurs de la 2.0.2 (*Mark of the Web*) est bien sûr inclus — voir
[`RELEASE_NOTES_v2.0.2.md`](RELEASE_NOTES_v2.0.2.md).
