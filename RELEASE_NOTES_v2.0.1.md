# Ghisdiag v2.0.1 — le bench thermique n'affirme plus ce qu'il n'a pas mesuré

Cette version corrige un défaut de fond : **le bench rendait des conclusions
qu'il n'avait jamais mesurées.**

Sur un portable dont Windows ne remonte aucune fréquence CPU, le rapport
affichait « Throttling thermique : **non** ». Une affirmation d'absence de
défaut — alors qu'aucune fréquence n'avait été relevée de tout le test. Un
outil de diagnostic qui rassure à tort fait suspecter du matériel sain, ou
dédouane du matériel qui chauffe vraiment.

L'installation ne change pas : c'est toujours l'archive `Ghisdiag.zip` à
décompresser, dossier entier à conserver.

---

## 🌡️ Ce qui change dans le bench thermique

### Le throttling a trois états, plus deux

`throttling` et `power_limited` valent désormais **oui / non / indéterminé**.
Ils ne se déduisent que d'une comparaison de fréquences : sans fréquence
exploitable, l'outil dit qu'il ne sait pas, et explique pourquoi.

**Les sessions déjà enregistrées sont relues correctement** — un
« throttling : non » archivé sans aucune fréquence relevée est requalifié en
indéterminé à l'affichage. Inutile de refaire les tests passés.

### Les fréquences reviennent sur les Intel récents

Depuis la 12ᵉ génération (Alder Lake), les capteurs de fréquence se nomment
`P-Core #N` et `E-Core #N`. Ghisdiag ne cherchait que `CPU Core #N` et n'en
trouvait aucun. Conséquence : **aucune fréquence relevée sur ces machines**, ce
qui désactivait silencieusement toute la détection de throttling — tout en
continuant d'afficher « Throttling : non ».

### Plus de « plateau » sur une charge écourtée

Le plateau et le ΔT étaient calculés sur le dernier tiers de la phase de charge.
Sur un test coupé au bout de 25 secondes sur 300, ce dernier tiers n'était que
le sommet d'une montée en température : l'outil annonçait un régime établi qui
n'avait jamais existé. Les deux valeurs sont maintenant laissées vides, avec
l'explication. La température **maximale** reste affichée : elle a bien été
atteinte.

### La limite de puissance est enfin détectée

Un portable qui plafonne parce qu'il applique sa limite de puissance (PL1/TDP)
affiche désormais :

> ℹ Limite de puissance atteinte : le CPU bride sa fréquence à charge soutenue.
> Normal — ce n'est pas un souci de refroidissement.

Auparavant cette limite passait inaperçue, et la température élevée pouvait
faire croire à une surchauffe.

### La comparaison avant/après vérifie les conditions de mesure

Elle ne regardait que le protocole *demandé* — durées, intensité — et ignorait
ce qui s'était *réellement passé*. Sont désormais contrôlés le noyau de charge,
les arrêts d'urgence, les interruptions, la durée de charge réellement tenue et
le refroidissement complet ou non.

Quand les conditions ne se comparent pas, le verdict ne chiffre plus de gain :
il annonce **« comparaison non concluante »** et détaille pourquoi. Le rapport
HTML gagne un tableau *« ce qui s'est réellement passé »*, affiché en toutes
circonstances.

---

## 🩺 Diagnostic

- **La cause d'un refus des capteurs remonte jusqu'à vous.** Le moteur savait
  pourquoi il échouait — DLL absente, ouverture du matériel impossible — mais
  jetait le message et affichait « les capteurs ne répondent pas ».
- **Le journal indique le contexte au démarrage** : version, exécutable compilé
  ou sources, **élévation**, dossier de pilotes actif. Sans élévation, l'accès
  aux registres du processeur est refusé et toute température CPU sort à N/A ;
  le journal le dit maintenant au lieu de le laisser deviner.
- **Le journal ne contient plus d'incidents fabriqués.** La suite de tests
  écrivait ses fausses pannes dans le journal réel de l'utilisateur et poussait
  dehors, par rotation, les lignes de vrai diagnostic.

### Trois outils d'atelier

| Outil | Usage |
|---|---|
| `collectors/dump_sensors.ps1` | Inventaire complet des capteurs vus par le backend, au repos puis sous charge. S'élève tout seul. |
| `collectors/dump_power_state.ps1` | Mode d'alimentation Windows, plafond du processeur, secteur/batterie. |
| `collectors/install_sensors_patch.ps1` | Pose un collecteur corrigé dans une installation déployée, sans recompiler. |

---

## 🔧 Réglage avancé

`GHISDIAG_EMERGENCY_TEMP_C` fixe le seuil d'arrêt d'urgence du bench CPU, borné
à **60-99 °C** — jamais au-delà du TjMax du processeur, dont la protection
matérielle reste de toute façon indépendante de Ghisdiag.

Utile sur les portables Intel P-series : leur première minute de charge se passe
en turbo, bien au-dessus de la puissance soutenue. Couper à 95 °C empêchait
d'atteindre le régime établi — c'est-à-dire précisément ce que le test doit
mesurer.

`GHISDIAG_LOG_DIR` déplace le journal et les préférences, pratique en usage
portable.

---

## ✅ Validation

Chaque correctif a été vérifié sur des sessions réelles et confronté à
**HWiNFO** sur la même machine au même instant.

| Machine | Régime établi | HWiNFO |
|---|---|---|
| Altyk i5-1240P | 28,1 W = sa puissance soutenue, 80 °C | 0/75 alerte thermique, 75/75 limite de puissance |
| MSI Core Ultra | 44,8 W, 79 °C | 0/64 thermique, 64/64 limite de puissance |
| Acer Ryzen 5 | 25 W, 81 °C | puissance au plafond, 0 alerte thermique |

Sur une paire de sessions où **rien n'avait été touché entre les deux mesures**,
l'ancienne version annonçait « −24 °C en charge, intervention efficace ». La
nouvelle répond « comparaison non concluante » et pointe la charge écourtée.

---

## 📥 Téléchargement

| | |
|---|---|
| **Fichier** | `Ghisdiag.zip` |
| **Taille** | `<TAILLE>` octets |
| **SHA-256** | `<SHA256>` |

> Ces valeurs portent sur l'archive **compilée par GitHub Actions** à partir du
> tag `v2.0.1` — celle qui est jointe à cette release et qui porte l'attestation
> de provenance. PyInstaller n'étant pas reproductible au bit près, une
> compilation locale du même code donnerait une empreinte différente : c'est
> normal, seule celle-ci fait foi.

Vérifier l'intégrité après téléchargement :

```powershell
Get-FileHash Ghisdiag.zip -Algorithm SHA256
```

Vérifier la provenance :

```powershell
gh attestation verify Ghisdiag.zip --repo ghislaindoucy/ghisdiag
```

**Prérequis :** Windows 10/11. Rien d'autre à installer.

---

## Reste ouvert

Le repos pollué n'est toujours pas signalé, l'affichage du ventilateur non
exposé reste ambigu, et la limite de puissance échappe encore à la détection sur
AMD — le boost s'y effondre plus vite que l'échantillonnage.
