# Configuration Mistral AI pour PlanetDiag

## Installation des dépendances

Pour utiliser la fonctionnalité d'analyse IA Mistral, installez les dépendances requises:

```bash
pip install requests cryptography
```

### Dépendances détaillées:
- **requests** (≥2.25.0): Client HTTP pour appels API Mistral
- **cryptography** (≥3.4): Chiffrement Fernet pour stockage sécurisé de la clé API

## Configuration

### 1. Obtenir une clé API Mistral

1. Créez un compte sur [Mistral AI Console](https://console.mistral.ai)
2. Générez une clé API dans les paramètres
3. Copiez votre clé API

### 2. Configurer dans PlanetDiag

1. Ouvrez PlanetDiag
2. Allez à l'onglet **"Analyse"** (onglet principal)
3. Dans le panneau "🤖 Analyse IA Mistral", entrez votre clé API
4. Cliquez sur **"Tester la clé"** pour vérifier la validité
5. La clé est automatiquement chiffrée et sauvegardée

### 3. Utilisation

- Chaque diagnostic lancé avec une clé API valide :
  - Génère le rapport standard HTML + JSON
  - Lance une analyse Mistral IA (en arrière-plan, non-bloquante)
  - Génère un rapport d'analyse `PlanetDiag_MACHINE_TIMESTAMP_AI_ANALYSIS.html`
  - Ouvre automatiquement le rapport d'analyse dans le navigateur

## Sécurité

### Chiffrement de la clé API

La clé API Mistral est **chiffrée** avant d'être sauvegardée:
- Utilise `cryptography.Fernet` (chiffrement symétrique AES-128)
- Clé de chiffrement dérivée du hostname + username (stable entre sessions)
- Jamais stockée en clair dans `%APPDATA%\Local\PlanetDiag\prefs.json`
- Déchiffrée en mémoire uniquement quand utilisée

### Bonnes pratiques

- 🔐 Protégez votre clé API comme un mot de passe
- 🗑️ Révoquez la clé depuis la console Mistral si compromise
- 💾 Le fichier `prefs.json` reste confidentiel (pas de partage)

## Tarification Mistral

PlanetDiag utilise le modèle **Mistral Large** pour les analyses:
- Coût approximatif: ~€0.004 par diagnostic (modèle large)
- Basé sur les tokens entrée/sortie
- Consultez [Mistral Pricing](https://mistral.ai/technology/pricing/)

Vous pouvez optimiser les coûts:
1. Utiliser une clé API avec budget limité
2. Réduire la verbosité du diagnostic avant envoi à Mistral
3. Contacter Mistral pour les volumes importants

## Dépannage

### "Modules Mistral non disponibles"

**Problème**: Le message d'erreur s'affiche au démarrage ou au test.

**Solutions**:
```bash
# Vérifier les installations
pip show requests cryptography

# Réinstaller les dépendances
pip install --upgrade requests cryptography

# Pour PyInstaller (executable PlanetDiag)
# Contactez les développeurs pour une réinstallation
```

### "Clé API invalide"

**Causes possibles**:
- Clé API incorrecte ou expirée
- Clé révoquée dans la console Mistral
- Problème de copier/coller (espaces supplémentaires)

**Solution**:
1. Vérifiez votre clé dans la console Mistral
2. Générez une nouvelle clé si nécessaire
3. Copiez la clé sans espaces avant/après
4. Testez à nouveau

### "Timeout - Impossible de contacter Mistral"

**Cause**: Connexion réseau lente ou API Mistral surchargée.

**Solution**:
1. Vérifiez votre connexion Internet
2. Réessayez dans quelques minutes
3. Vérifiez le [statut Mistral](https://status.mistral.ai)

### "Analyse Mistral vide ou incomplète"

**Cause**: L'API Mistral n'a pas retourné de contenu.

**Solution**:
1. Vérifiez les logs dans le fichier log de PlanetDiag
2. Réessayez le diagnostic
3. Contactez le support Mistral si le problème persiste

## API Mistral utilisée

```
Endpoint: https://api.mistral.ai/v1/chat/completions
Modèle: mistral-large-latest
Timeout: 90 secondes
Max tokens réponse: 4096
Temperature: 0.7
```

## Fichiers générés

Après chaque diagnostic avec clé API valide:

```
📁 Documents/PlanetDiag_Reports/
├── PlanetDiag_LAPTOP-ABC_20260603_143056.html          # Rapport technique
├── PlanetDiag_LAPTOP-ABC_20260603_143056.json          # Données brutes
└── PlanetDiag_LAPTOP-ABC_20260603_143056_AI_ANALYSIS.html  # Analyse Mistral ✨
```

Le rapport `_AI_ANALYSIS.html` contient:
- Résumé exécutif
- État du système (OK/Attention/Critique)
- Problèmes détectés avec impact
- Conseils de réparation détaillés
- Optimisations recommandées
- Services à gérer
- Recommandations matériel

## Support

Pour les problèmes:
1. Consultez cette documentation
2. Vérifiez les logs dans `%APPDATA%\Local\PlanetDiag\planetdiag.log`
3. Contactez le support PlanetDiag
