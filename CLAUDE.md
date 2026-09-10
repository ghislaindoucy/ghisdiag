# Ghisdiag — instructions de travail

Outil de **diagnostic et de maintenance Windows tout-en-un** pour technicien SAV, compilé en
un dossier portable (PyInstaller onedir, ~34 Mo zippé), sans dépendance à installer sur la
machine cible. Interface tkinter, 5 onglets. Dépôt public, licence PolyForm Noncommercial.

**Le module disque a son propre dépôt depuis le 10/09/2026** : GhisdiagDisk vit dans
`D:\Projets\GhisdiagDisk` (`github.com/ghislaindoucy/ghisdiagdisk`, privé). Tout travail sur
le test de surface, le balayage, le rapport disque ou WinPE se fait **là-bas**, pas ici. Les
deux outils sont complémentaires et n'ont **aucune dépendance de code** : l'import du
diagnostic disque (v2.3.0) se fera par fichier JSON, jamais par import.

## Commandes

```bash
py -m unittest discover -s tests              # suite complète
py -m pyflakes <fichiers touchés>             # AVANT chaque commit
py -m PyInstaller --clean --noconfirm Ghisdiag.spec
```

La commande Python est **`py`**, jamais `python`. `build.bat` fait le build complet (spec +
notice + zip) ; depuis Git Bash il faut `cmd //c`, pas `cmd /c`, sinon il ouvre un shell
interactif et attend indéfiniment.

## Conventions

- Les collecteurs `.ps1` sont en **ASCII strict** (règle inscrite dans leur en-tête) : pas de
  guillemets français, pas de tiret cadratin.
- Commentaires en français, qui expliquent le **pourquoi**.
- Ne **jamais** bumper la version sans demande explicite.

## Règles propres à ce projet

1. **Release : la version vit à 4 endroits dans le code** (`orchestrator.py`,
   `report/generator.py`, `version_info.txt`, `Ghisdiag.manifest`) plus les docs (CHANGELOG,
   RELEASE_NOTES, badge et changelog du README, ROADMAP, notice). Elles dérivent facilement.
2. **SHA-256 et taille se mesurent juste avant `gh release create`**, sur le fichier exact
   qu'on téléverse : PyInstaller n'est pas reproductible, deux builds donnent deux binaires.
   Renommer l'archive en `Ghisdiag.zip` **avant** l'upload — le `#` de `gh` ne définit qu'un
   libellé, pas le nom de l'asset.
3. **Mark of the Web** : une DLL extraite d'une archive téléchargée par navigateur puis
   Explorateur Windows est bloquée, et tous les capteurs meurent. Tester le **geste réel de
   l'utilisateur**, jamais un chemin « équivalent » (`gh release download` ne pose pas de MotW).
4. **Vérifier le fichier produit, pas le code retour.** Le PDF de notice est sorti vide à
   24 Ko avec un exit code 0. Contrôler taille et contenu.
5. **Une donnée de diagnostic visiblement fausse est un bug**, pas du bruit à filtrer.
6. **Ancrer une fenêtre d'analyse sur une observation**, jamais sur une horloge qui suppose
   que la charge a démarré.
7. **Toute valeur d'exception utilisée dans un callback différé se copie dans une variable
   locale** : Python supprime la variable du `except` à la sortie du bloc.
8. **Quand un test qu'on vient d'écrire échoue, suspecter le test d'abord.**
9. **Un seul shell par commande.** Bash → heredoc `<<'EOF'`, `cmd //c`. PowerShell → `@'…'@`,
   pas de `&&`.
10. **Un processus long écrit dans un fichier journal** lisible pendant qu'il tourne, jamais
    dans un `| tail` qui ne rend rien avant la fin.

## Où est quoi

| | |
|---|---|
| `ROADMAP.md` | état de l'application, roadmap par version, décisions et leur pourquoi. Fait foi. |
| `CHANGELOG.md` | une entrée par version publiée |
| `orchestrator.py` | enchaînement des collecteurs |
| `collectors/` | capteurs, températures, SMART, bench thermique |
| `report/generator.py` | rapport HTML + JSON |
| `ai_attachments.py` | pièces jointes du diagnostic IA (patron du futur `digest_disque()`) |
| `docs/antivirus-guide.md` | attestation de provenance, faux positifs |

Validation : Ghislain teste sur un **parc de machines physiques réelles en atelier** avant
toute release. Les mesures d'atelier priment sur toute déduction.
