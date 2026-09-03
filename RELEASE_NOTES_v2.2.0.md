# Ghisdiag v2.2.0 — le bench thermique du jour rejoint l'audit IA

Jusqu'ici, l'audit IA raisonnait sur un **instantané** : les collecteurs du
diagnostic, pris au repos. Or quand un bench thermique vient d'être joué sur la
machine, on dispose d'une **mesure sous charge** — la donnée la plus parlante
pour juger un refroidissement, et l'IA ne la voyait pas. Cette version la lui
donne, sans rien changer à l'audit quand il n'y a pas de bench.

---

## Ce qui est joint, et quand

- **Le bench du jour, et rien d'autre.** On benche et on diagnostique dans la
  même passe. Un bench d'hier n'est jamais joint : une fenêtre plus large
  finirait par faire conclure l'IA sur un état d'avant intervention. Sans bench
  du jour, aucune pièce jointe, et l'audit est **exactement** celui d'avant.
- **CPU et GPU ensemble** quand les deux existent : deux mesures indépendantes,
  et leur écart est lui-même un signal.
- **Un « avant » et un « après » le même jour donnent le delta**, celui de la
  comparaison avant/après, avec ses réserves et son verdict — pas les deux
  sessions.
- **Un digest, pas la session brute** : températures de repos, plateau et
  maximum, ΔT, ventilateurs, fréquences, throttling, limite de puissance, état
  de déroulement du test, et une **courbe ré-échantillonnée à 20 points** qui
  donne la forme de la rampe et du plateau.

## Ce que l'IA a interdiction de faire

Le bench distingue soigneusement « pas de throttling » de « non mesuré » (charge
écourtée, test interrompu, arrêt d'urgence, fréquence illisible). Cette
distinction **survit au transfert** : le throttling et la limite de puissance
sont transmis « oui », « non » ou « non mesuré » avec la raison, et le prompt
interdit à l'IA d'en tirer un verdict, positif ou négatif. Un test qui n'a
jamais atteint son régime établi ne fera jamais écrire « refroidissement sain ».

Le prompt système gagne aussi des **seuils thermiques de référence** (plateau
CPU, throttling à 90 °C, GPU et hotspot) et dit explicitement qu'une **limite
de puissance est un comportement normal** (PL1/TDP), pas un défaut. Un domaine
« Thermique (bench du jour) » apparaît dans la revue par domaine — « non testé »
sans pièce jointe, jamais « sain » — et la section Matériel & durée de vie s'en
sert comme argument chiffré d'un nettoyage ou d'un changement de pâte.

## Vous voyez ce que l'IA a vu

- Dans le panneau « Analyse IA », avant de lancer : **« 📎 Bench du jour joint à
  l'audit : CPU 14:32, GPU 15:10 »**, ou « Aucun bench thermique du jour à
  joindre ». Rafraîchi après chaque bench.
- Dans le journal et dans l'**en-tête du rapport IA** : la ligne « Pièces
  jointes », y compris « aucune ». Un audit qui parle de throttling est
  vérifiable.

## Corrigé au passage : les erreurs de l'analyse IA s'affichent enfin

Clé invalide, timeout ou panne réseau pendant l'audit IA : jusqu'ici la popup
d'attente se fermait et **rien** n'apparaissait, ni dans le journal ni à
l'écran. Le message était différé vers l'interface par une fonction qui lisait
la variable d'exception après que Python l'avait supprimée. Corrigé, ainsi que
le même défaut sur l'erreur fatale du diagnostic, où le bouton « Réessayer » ne
revenait jamais.

## Sous le capot

- La pièce jointe est un **bloc séparé, placé avant le JSON du diagnostic, avec
  son propre budget**. Le prompt est plafonné à 120 000 caractères et la
  troncature coupe la fin : une pièce glissée dans les données aurait été la
  première sacrifiée, en silence. Seul le diagnostic se tronque désormais.
- Le mécanisme est **générique** : l'outil disque GhisdiagDisk s'y branchera.
- 21 tests sans matériel ni réseau, et rejeu des sessions réelles archivées.

---

## Installation

Archive portable `Ghisdiag.zip` : extraire, lancer `Ghisdiag.exe` (élévation
demandée). Pas d'installation. La notice PDF est dans l'archive, à côté de
l'exécutable.

## Empreinte de l'archive publiée

Archive compilée et attestée par la CI GitHub sur le commit de merge
`a16246657fee1dcd7848504d14d269831b6421e5` (workflow `build-release.yml`,
`refs/tags/v2.2.0`).

- **Fichier** : `Ghisdiag.zip`
- **SHA-256** : `d536365d625a80eaf1f884f040d558af9953fbd99e20c8de9e35b8dc3a2ebe12`
- **Taille** : 36 478 953 octets (34,8 Mo)

```powershell
Get-FileHash Ghisdiag.zip -Algorithm SHA256
```

Attestation de provenance SLSA : `gh attestation verify Ghisdiag.zip --owner ghislaindoucy`.
