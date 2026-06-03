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
MAX_OUTPUT_TOKENS = 15000  # marge confortable pour un audit détaillé (fenêtre modèle 128k)
# Un audit de 15k tokens peut prendre plusieurs minutes à générer. L'appel tournant
# dans un thread de fond (UI non bloquée), on laisse une marge large.
MISTRAL_TIMEOUT = 240  # secondes


SYSTEM_PROMPT = """Tu es un expert en systèmes Windows, spécialisé dans le support technique (SAV) et l'analyse de données informatiques.

Tu vas analyser les données de diagnostic transmises et générer un audit complet détaillé.

Pour chaque problème identifié, tu dois:
1. Expliquer clairement le problème
2. Évaluer son impact (Critique/Grave/Moyen/Faible)
3. Donner des conseils de réparation détaillés avec étapes précises
4. Proposer des optimisations du système
5. Fournir les démarches step-by-step pour chaque action
6. Identifier les services à désactiver ou mettre à jour
7. Recommander du matériel si nécessaire

Formate ta réponse de manière lisible avec des titres, listes et sections claires."""


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
        max_len = 60000  # ~15k tokens
        if len(diag_json) > max_len:
            logger.warning(f"Données diagnostiques tronquées ({len(diag_json)} chars → {max_len})")
            diag_json = diag_json[:max_len] + "\n[… données tronquées …]"

        user_prompt = f"""Voici les données de diagnostic de ce système Windows:

```json
{diag_json}
```

Fournis un audit complet et structuré avec:
1. **Résumé Exécutif** - Vue d'ensemble du système en 2-3 lignes
2. **État du système** - OK / Attention / Critique
3. **Problèmes détectés** - Les 5 principaux problèmes avec impact
4. **Conseils de réparation** - Démarches détaillées pour chaque problème
5. **Optimisations recommandées** - Actions pour améliorer les performances
6. **Services à gérer** - Services à désactiver/mettre à jour
7. **Recommandations matériel** - Si applicable"""

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
            "temperature": 0.7,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "top_p": 0.95,
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
