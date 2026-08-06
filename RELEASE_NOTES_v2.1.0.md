# Ghisdiag v2.1.0 — l'onglet Setup en tête, l'heure et la veille sous la main

Cette version part de l'usage réel en atelier : on branche une machine
fraîchement réinstallée, et les deux premières choses qui manquent sont
l'**heure** et l'assurance que le PC ne va pas **s'endormir** au milieu de
l'intervention. Ni l'une ni l'autre n'existait dans Ghisdiag — il fallait en
sortir.

---

## « Setup / MAJ » devient le premier onglet

Il était le cinquième et dernier. C'est pourtant l'onglet du premier geste :
mise à l'heure, comptes, logiciels essentiels. Il passe en tête, et
l'application s'ouvre désormais dessus. L'ordre des autres onglets ne change
pas.

## Régler l'heure, la date et le fuseau horaire

Nouveau sous-onglet **« Heure & veille »**, en tête du Setup.

Une horloge fausse n'est pas un détail de confort : winget refuse de fonctionner,
l'activation Windows échoue et **toute connexion HTTPS est rejetée** parce que les
certificats paraissent invalides. C'est le préalable à tout le reste.

- **Horloge vivante** — jour, date et heure à la seconde, en toutes lettres. À
  côté : le fuseau actif, la source de temps déclarée par Windows et l'état du
  service W32Time.
- **Deux chemins, volontairement indépendants.**
  - *Synchroniser sur Internet* cale l'horloge sur un serveur NTP
    (`time.windows.com`, `fr.pool.ntp.org`, `pool.ntp.org`).
  - *Saisie manuelle* règle date et heure à la main.

  Le second n'est pas un repli de dépit : en atelier, la machine sort d'une
  réinstallation et **n'a pas encore de réseau** — c'est le cas courant, pas
  l'exception. La synchronisation n'est donc jamais un passage obligé, et quand
  elle échoue (pas de connexion, port 123 filtré), le message renvoie
  explicitement vers la saisie manuelle au lieu de laisser l'utilisateur devant
  une impasse.
- **Fuseau horaire** — la liste Windows complète (~140 entrées), positionnée
  d'office sur celui de la machine. Un fuseau erroné décale l'horloge d'une heure
  entière **même après une synchronisation réussie** : le symptôme ressemble à
  une synchro qui n'a pas marché, la cause est ailleurs.
- **Machine membre d'un domaine** : c'est détecté, et signalé. La hiérarchie de
  temps y est imposée par l'annuaire ; Ghisdiag ne réécrit pas la liste de pairs
  NTP et se contente de demander un rafraîchissement.

Garde-fous : la date saisie est validée avant d'être appliquée (format, date
impossible comme le 29 février d'une année non bissextile, année hors
2000-2100), puis **confirmée en toutes lettres** — une faute de frappe ne doit
pas envoyer la machine en 2027. Côté PowerShell, les identifiants de fuseau sont
vérifiés contre la liste système et les noms de serveur contre un motif strict.

## Empêcher la mise en veille

Un interrupteur dans le même sous-onglet, avec une option « garder aussi l'écran
allumé ». Utile pendant une installation, une copie longue, un test.

**Le bench thermique l'active tout seul, le temps du test.** C'est la vraie
raison de cette fonction : un bench dure jusqu'à ~17 minutes sans la moindre
interaction clavier ou souris. Rien n'empêchait jusqu'ici la machine de
s'endormir en pleine phase de charge — la mesure était coupée et la session
inexploitable.

- L'interrupteur du technicien et le bench portent des **demandes distinctes** :
  la fin du test ne retire pas un blocage posé à la main.
- Windows n'accorde ce blocage que **le temps de vie du programme qui le
  demande**. Il s'arrête donc à la fermeture de Ghisdiag — l'interface le dit
  plutôt que de laisser croire à un réglage permanent.
- Si Windows refuse la demande, la case revient d'elle-même sur « inactif ».
  Afficher un blocage qui n'a pas eu lieu serait pire que ne rien afficher.

## La notice est livrée avec l'application

`Notice_Ghisdiag.pdf` est désormais présente **à côté de `Ghisdiag.exe`** dans
l'archive comme sur la clé USB d'atelier. Préparé en 2.0.3, effectif à partir de
ce build.

---

## 📥 Téléchargement

| | |
|---|---|
| **Fichier** | `Ghisdiag.zip` |
| **Taille** | `36 339 603` octets (34,7 Mo) |
| **SHA-256** | `7DA2561B8AA8C91A3DA1B1FA0E29EEDE487040103DB07174177BD2AE7285DAE5` |

> Ces valeurs portent sur l'archive **compilée par GitHub Actions** à partir du
> tag `v2.1.0` — celle qui est jointe à cette release et qui porte l'attestation
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
