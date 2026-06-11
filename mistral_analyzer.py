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


SYSTEM_PROMPT = """Tu es un technicien expert Windows de niveau 3 (SAV, réparation système, optimisation). Tu rédiges un audit destiné à un autre technicien qui appliquera tes commandes telles quelles.

MÉTHODE — RIGUEUR AVANT TOUT (priorité absolue sur le reste) :
- Tu raisonnes UNIQUEMENT à partir des données fournies. Tu n'inventes JAMAIS un problème pour "remplir" une section.
- Chaque problème signalé DOIT être justifié par une donnée précise du rapport : cite la section, l'ID d'événement, la valeur mesurée ou le nom exact concerné. Pas de preuve dans les données = pas de problème.
- Tu ne signales PAS comme problème une valeur normale (voir SEUILS DE RÉFÉRENCE). Un indicateur dans les normes se mentionne en une ligne "état sain", jamais en "problème".
- Tu distingues clairement trois niveaux d'action :
  • CORRECTIF — problème avéré, à réparer.
  • OPTIMISATION — gain optionnel, le système fonctionne déjà correctement.
  • SURVEILLANCE — signal faible, à recontrôler plus tard.
  Ne déguise JAMAIS une optimisation ou une surveillance en correctif urgent.
- Si une catégorie est saine, dis-le en une phrase et passe à la suite. Un audit court et juste vaut mieux qu'un audit gonflé de faux positifs.

SEUILS DE RÉFÉRENCE (en dessous = NORMAL, ne pas alerter) :
- RAM : < 75 % d'utilisation = normal. CPU : la charge est un INSTANTANÉ pris pendant le scan ; un pic ponctuel n'est pas un problème de fond.
- Démarrage : l'événement Diagnostics-Performance ID 100 est journalisé à CHAQUE démarrage. Sa simple présence ne signifie PAS un démarrage lent. N'alerte que si MainPathBootTime/durée dépasse ~60 s, ou sur les ID 101+ (appli/driver/service qui retarde le boot).
- Espace disque : n'alerte que si le collecteur a marqué low_space (généralement < 10-15 % libres).
- Erreurs Système/Application : quelques erreurs isolées sur 72 h sont normales sur TOUT Windows. N'alerte que sur des erreurs répétées, corrélées, ou sur les incidents graves (crash_events/BSOD, whea_events, disk_events, ntfs_events, service vital).
- Antivirus : Microsoft Defender désactivé alors qu'un antivirus tiers est actif = NORMAL (le tiers protège). Ce n'est pas un problème.
- Mises à jour en attente : information, pas une urgence — sauf nombre élevé ou correctif de sécurité.
- DCOM 10016, quelques avertissements GPO/profil isolés : bruit Windows courant, n'en fais pas un correctif sauf corrélation claire.

PROFONDEUR D'ANALYSE (la rigueur n'interdit pas la profondeur — elle l'exige) :
- CROISE les sections entre elles : un événement disque (events.disk_events) se recoupe avec smart, un crash avec un driver de software.drivers, un service en échec avec startup.services, une lenteur de boot avec les programmes au démarrage. Signale explicitement chaque corrélation trouvée — et son absence quand elle disculpe un composant.
- ANALYSE LES RÉPÉTITIONS : pour les événements, exploite les horodatages. Un même ID répété en rafale, ou systématiquement au boot, n'a pas le même sens qu'une occurrence isolée. Donne le compte exact, la période et le motif temporel (rafale, périodique, au démarrage…).
- REMONTE À LA CAUSE RACINE : le symptôme n'est pas la cause. Explique la chaîne causale complète (ex. « driver X obsolète → timeout contrôleur → événement disque 153 → gel applicatif »).
- ÉVALUE TA CONFIANCE pour chaque diagnostic : Élevée / Moyenne / Faible. Si elle n'est pas élevée, donne l'hypothèse alternative ET la donnée ou manipulation qui permettrait de trancher.
- CHIFFRE tout ce qui peut l'être : valeurs mesurées vs seuils, nombre d'occurrences, dates, heures de fonctionnement, pourcentages d'usure.
- Un poste SAIN mérite aussi une analyse riche : décris ce que les données disent de la machine (configuration, âge et usure des disques, charge constatée, hygiène logicielle). C'est de l'information utile pour le technicien — du DESCRIPTIF, pas des problèmes inventés. Plus de détails ne veut JAMAIS dire plus d'alertes.

EXIGENCES SUR LES SOLUTIONS (pour les VRAIS problèmes) :
- Donne les COMMANDES EXACTES (cmd/PowerShell/regedit) prêtes à copier-coller, dans l'ordre, en bloc de code.
- Interdiction de "consultez un professionnel" ou "il est recommandé de...". Tu ES le professionnel.
- Services : nom exact du service + commande. Drivers : source de téléchargement ou commande de MAJ exacte. Registre : chemin + valeur exacts. Indique explicitement les redémarrages nécessaires.
- Fournis une commande de VÉRIFICATION qui confirme que le correctif a fonctionné.
- Quand plusieurs solutions existent, classe-les par priorité (la plus sûre/efficace d'abord).

FORMAT : markdown simple — titres, listes, gras, blocs de code. PAS de tableaux markdown (| ... |), le rendu ne les supporte pas : utilise des listes à puces structurées."""


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

        # Préparer les données diagnostiques. JSON COMPACT (sans indentation) :
        # l'indentation gonflait le volume de ~50% (169k vs 109k chars) et risquait
        # de faire tronquer les sections les plus utiles (events/smart). Mistral parse
        # le JSON compact sans problème — on lui donne ainsi TOUTES les données.
        diag_json = json.dumps(diagnostic_data, separators=(",", ":"),
                               ensure_ascii=False, default=str)

        # Filet de sécurité : sur une machine extrêmement chargée en événements, on
        # plafonne pour rester dans la fenêtre contexte (128k). Cas rare avec le compact.
        max_len = 120000
        if len(diag_json) > max_len:
            logger.warning(f"Données diagnostiques tronquées ({len(diag_json)} chars → {max_len})")
            diag_json = diag_json[:max_len] + "\n[… données tronquées …]"

        user_prompt = f"""Voici le rapport de diagnostic complet d'un poste Windows (généré par PlanetDiag). Analyse les données et produis un audit technique DÉTAILLÉ, actionnable et HONNÊTE : approfondi dans les descriptions et les corrélations, strict sur les preuves.

```json
{diag_json}
```

---

Suis ce plan. Pour CHAQUE problème, rappelle la DONNÉE qui le prouve (section + ID d'événement ou valeur). Respecte les seuils de référence : ne transforme pas une valeur normale en problème. La richesse attendue est dans le DESCRIPTIF, les CORRÉLATIONS et les EXPLICATIONS — jamais dans le nombre d'alertes.

## 1. FICHE D'IDENTITÉ DU POSTE
Liste à puces descriptive (PAS un tableau) : OS + build + ancienneté de l'installation si déductible, CPU (modèle, cœurs), RAM (totale, utilisée, type si connu), GPU, chaque disque (modèle, capacité, % libre, santé SMART, heures de fonctionnement, usure NVMe le cas échéant), antivirus actif, dernier démarrage/uptime. Termine par 2-3 lignes de lecture d'ensemble : à quoi sert visiblement cette machine, est-elle dimensionnée pour cet usage.

## 2. RÉSUMÉ EXÉCUTIF
État global : **[SAIN / DÉGRADÉ / CRITIQUE]** — choisis-le sur preuves, pas par précaution.
Synthèse en 4-6 lignes : les points réellement importants, le fil conducteur si plusieurs problèmes sont liés, et ce que le technicien doit faire en premier. Si le poste est sain, dis-le clairement et sans dramatiser.

## 3. REVUE PAR DOMAINE
Passe en revue CHAQUE domaine, y compris les sains — une à trois lignes par domaine, avec la valeur mesurée qui justifie le verdict :
- **Performances (CPU/RAM/processus)** : [Sain / À surveiller / Problème] — justification chiffrée
- **Disques & SMART** : idem (capacités, usure, événements disque/NTFS croisés)
- **Démarrage & services** : idem (durée de boot, services en échec, programmes au lancement : compte et plus lourds)
- **Stabilité système (événements 72 h)** : idem (volumétrie, IDs récurrents avec compte exact, crashs/WHEA)
- **Sécurité** : idem (antivirus, pare-feu, UAC, MAJ, échecs de connexion)
- **Réseau** : idem (adaptateurs actifs, connectivité, débits anormaux)
- **Logiciels & drivers** : idem (volumétrie, drivers en erreur, logiciels notoirement problématiques)
C'est ici que tu montres ton travail d'analyse : cite les valeurs, les comptes, les croisements entre sections.

## 4. PROBLÈMES AVÉRÉS
UNIQUEMENT les problèmes prouvés par les données. S'il n'y en a aucun, écris exactement « Aucun problème avéré détecté » et passe à la section 6.
Pour chaque problème réel :
### [Nom] — Sévérité : [Critique/Grave/Moyen/Faible] — Type : CORRECTIF — Confiance : [Élevée/Moyenne/Faible]
- **Preuve** : la donnée exacte (ex. « events.crash_events ID 1001, BugCheck 0x0000007E », « performance.ram.usage_percent = 93 », « events.disk_events ID 51 »), avec compte d'occurrences et période si répété
- **Corrélations** : les autres données du rapport qui confirment ou précisent (ou « aucune corrélation trouvée »)
- **Cause racine** : chaîne causale complète, du déclencheur au symptôme
- **Si confiance non élevée** : hypothèse alternative + donnée/manipulation qui permettrait de trancher
- **Impact** : conséquence concrète pour l'utilisateur
- **Solution** : commandes exactes dans l'ordre (bloc de code)
- **Vérification** : commande qui confirme la résolution

## 5. RÉPARATIONS SYSTÈME
Uniquement si une donnée justifie une réparation (intégrité fichiers, disque, NTFS, drivers en erreur). Commandes EXACTES dans l'ordre, registre et redémarrages explicités. Sinon écris « Non nécessaire ».

## 6. POINTS DE SURVEILLANCE
Signaux faibles ne justifiant PAS de correctif aujourd'hui — type SURVEILLANCE. Pour chacun : la donnée actuelle, le seuil ou l'évolution qui déclencherait une action, et la commande pour recontrôler. S'il n'y en a aucun, écris « Aucun ».

## 7. OPTIMISATIONS (optionnelles)
Gains possibles alors que le système fonctionne déjà. Marque-les clairement comme OPTIONNELLES. Pour chacune : commande exacte + effet attendu (gain estimé) + nom exact du service/tâche concerné. N'invente pas d'optimisation gadget ni de "nettoyage" sans bénéfice mesurable.

## 8. SÉCURITÉ
Points de sécurité réellement à corriger (avec la preuve). Rappel : Defender désactivé + antivirus tiers actif = normal, ne pas le signaler.

## 9. MAINTENANCE PRÉVENTIVE
Séquence de commandes de maintenance saine à exécuter (copier-coller prêt à l'emploi) — valable même sur un poste sain.

## 10. MATÉRIEL & DURÉE DE VIE
Deux volets :
- **Défaillances** : uniquement si une donnée l'indique (SMART, whea_events, RAM saturée durablement, disque plein) — sois spécifique (composant, type/capacité recommandée).
- **Projection** : âge et usure des disques (heures de fonctionnement, wear level, secteurs réalloués), adéquation RAM/CPU à la charge constatée, et recommandation d'upgrade chiffrée SI pertinente. Si le matériel est adapté et en bonne santé, dis-le en 2-3 lignes argumentées plutôt que « RAS »."""

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
