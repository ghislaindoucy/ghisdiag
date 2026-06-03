"""
PlanetDiag - Analyseur Mistral AI
Envoie les données diagnostiques à Mistral pour une analyse experte.
"""

import json
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_MODEL = "mistral-large-latest"
MAX_OUTPUT_TOKENS = 20000  # audit complet et détaillé (fenêtre modèle 128k)
# À 20k tokens de sortie la génération peut dépasser 5 min sur Mistral Large.
# L'appel tourne en thread de fond (UI non bloquée), marge large.
MISTRAL_TIMEOUT = 300  # secondes


SYSTEM_PROMPT = """Tu es un technicien expert Windows de niveau 3, spécialisé en SAV, réparation système et optimisation de postes de travail.

RÈGLES ABSOLUES — respecte-les sans exception :
- Chaque problème identifié doit aboutir à UNE SOLUTION CONCRÈTE ET APPLICABLE.
- Interdiction de répondre "consultez un professionnel" ou "il est recommandé de...".
- Chaque solution doit inclure les COMMANDES EXACTES à exécuter (cmd, PowerShell, regedit, etc.).
- Si plusieurs solutions existent, donne-les par ordre de priorité avec la commande précise pour chacune.
- Pour les services : donne le nom exact du service ET la commande pour le désactiver/arrêter.
- Pour les drivers : donne la source exacte de téléchargement ou la commande de mise à jour.
- Pour les erreurs événements : donne la cause probable ET la démarche de résolution commande par commande.
- Pour les optimisations : donne les commandes PowerShell/cmd exactes, pas des clics dans l'interface.
- Utilise des blocs de code pour toutes les commandes.
- Sois exhaustif : mieux vaut trop de détails que des instructions vagues."""


def analyze_diagnostic(
    diagnostic_data: dict,
    mistral_api_key: str,
    progress_callback: Optional[callable] = None,
) -> Optional[str]:
    """
    Envoie les données diagnostiques à Mistral pour une analyse complète.

    Args:
        diagnostic_data: dict complet retourné par DiagnosticOrchestrator.run()
        mistral_api_key: Clé API Mistral (déchiffrée)
        progress_callback: Fonction pour mettre à jour la progression (optionnel)

    Returns:
        Texte de la réponse Mistral (markdown), ou None en cas d'erreur
    """
    try:
        if progress_callback:
            progress_callback("Préparation des données pour Mistral…")

        # Préparer les données diagnostiques
        diag_json = json.dumps(diagnostic_data, indent=2, ensure_ascii=False, default=str)

        # Limiter la taille pour ne pas dépasser le context window
        # On monte à 80k chars pour donner le plus de contexte possible à Mistral
        max_len = 80000
        if len(diag_json) > max_len:
            logger.warning(f"Données diagnostiques tronquées ({len(diag_json)} chars → {max_len})")
            diag_json = diag_json[:max_len] + "\n[… données tronquées …]"

        user_prompt = f"""Voici le rapport de diagnostic complet d'un poste Windows. Analyse chaque section et génère un audit technique actionnable.

```json
{diag_json}
```

---

Génère l'audit selon ce plan OBLIGATOIRE. Pour chaque section, sois exhaustif et précis.

## 1. RÉSUMÉ EXÉCUTIF
État global : **[SAIN / DÉGRADÉ / CRITIQUE]**
Synthèse en 3-4 lignes des points les plus importants.

## 2. PROBLÈMES IDENTIFIÉS
Pour CHAQUE problème trouvé dans les données, structure-le ainsi :
### [Nom du problème] — Sévérité : [Critique/Grave/Moyen/Faible]
- **Cause** : explication précise de ce qui se passe
- **Impact** : conséquence concrète pour l'utilisateur
- **Solution immédiate** : commandes exactes à exécuter maintenant
- **Vérification** : commande pour confirmer que le problème est résolu

## 3. RÉPARATIONS SYSTÈME
Pour chaque réparation nécessaire, donne les commandes EXACTES dans l'ordre :
- Commandes cmd/PowerShell avec les paramètres complets
- Chemins de registre si applicable avec les valeurs à modifier
- Redémarrages nécessaires indiqués explicitement

## 4. OPTIMISATIONS PERFORMANCES
Actions concrètes pour améliorer les performances, avec pour chacune :
- La commande PowerShell ou cmd exacte
- L'effet attendu (gain estimé)
- Les services/tâches à désactiver avec leur nom exact de service Windows

## 5. SÉCURITÉ
Points de sécurité à corriger basés sur les données, avec les commandes de correction.

## 6. MAINTENANCE PRÉVENTIVE
Séquence de commandes de maintenance à exécuter immédiatement (copier-coller prêt à l'emploi).

## 7. RECOMMANDATIONS MATÉRIEL
Uniquement si les données indiquent un composant défaillant ou insuffisant — sois spécifique (type/capacité recommandée)."""

        if progress_callback:
            progress_callback("Envoi des données à Mistral…")

        headers = {
            "Authorization": f"Bearer {mistral_api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": MISTRAL_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,   # faible = réponses factuelles et précises (moins de "créativité")
            "max_tokens": MAX_OUTPUT_TOKENS,
            "top_p": 0.9,
        }

        response = requests.post(
            MISTRAL_API_URL,
            json=payload,
            headers=headers,
            timeout=MISTRAL_TIMEOUT,
        )

        if progress_callback:
            progress_callback(f"Traitement de la réponse Mistral…")

        # Vérifier le statut HTTP
        if response.status_code == 401:
            logger.error("Erreur authentification Mistral: clé API invalide")
            raise ValueError("Clé API Mistral invalide")

        if response.status_code == 429:
            logger.warning("Rate limit Mistral: trop de requêtes")
            raise RuntimeError("Mistral: limite de requêtes atteinte, réessayez dans quelques secondes")

        if response.status_code != 200:
            logger.error(f"Erreur Mistral {response.status_code}: {response.text}")
            raise RuntimeError(f"Erreur Mistral: {response.status_code}")

        # Extraire le texte de la réponse
        response_json = response.json()

        if "choices" not in response_json or len(response_json["choices"]) == 0:
            logger.error(f"Réponse Mistral invalide: {response_json}")
            raise RuntimeError("Format de réponse Mistral invalide")

        analysis_text = response_json["choices"][0]["message"]["content"]

        logger.info("Analyse Mistral complétée avec succès")
        return analysis_text

    except requests.exceptions.Timeout:
        logger.error(f"Timeout lors de l'appel Mistral (>{MISTRAL_TIMEOUT}s)")
        raise RuntimeError("Timeout Mistral - L'analyse a pris trop de temps. Réessayez plus tard.")

    except requests.exceptions.ConnectionError as e:
        logger.error(f"Erreur de connexion Mistral: {e}")
        raise RuntimeError(f"Impossible de contacter Mistral: {e}")

    except json.JSONDecodeError as e:
        logger.error(f"Erreur parsing JSON Mistral: {e}")
        raise RuntimeError(f"Erreur parsing réponse Mistral: {e}")

    except (ValueError, RuntimeError):
        # Erreurs déjà typées et formatées (clé invalide, rate limit, etc.) :
        # on les laisse remonter telles quelles pour que l'appelant les distingue.
        raise

    except Exception as e:
        logger.exception("Erreur inattendue lors de l'analyse Mistral")
        raise RuntimeError(f"Erreur analyse Mistral: {e}")
