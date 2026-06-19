"""
Ghisdiag - Analyseur IA multi-fournisseurs.

Envoie les données diagnostiques à un fournisseur IA pour une analyse experte.
Tout en HTTP brut via `requests` — AUCUN SDK (anthropic/openai/...) : ça gonflerait
l'exe onefile. Le prompt tuné est mutualisé et réutilisé à l'identique par tous
les fournisseurs, c'est lui qui garantit la qualité quel que soit le modèle.

Trois familles d'API couvrent les fournisseurs envisagés (1 fonction par famille) :
  - "openai"    → /v1/chat/completions, header Authorization: Bearer,
                  réponse choices[0].message.content
                  Couvre Mistral, OpenAI et Grok (xAI, api.x.ai/v1, compatible OpenAI).
  - "anthropic" → /v1/messages, headers x-api-key + anthropic-version,
                  `system` séparé des `messages`, réponse content[0].text.
  - "gemini"    → Google AI, clé en ?key=, system_instruction + contents/parts,
                  réponse candidates[0].content.parts[].text.

Les 5 fournisseurs sont branchés (Anthropic, Mistral, OpenAI, Grok, Gemini).
Le chemin "openai" est paramétrable par fournisseur via PROVIDERS :
  - max_tokens_param : "max_tokens" (Mistral) ou "max_completion_tokens" (GPT-5/Grok 4).
  - sampling : True pour envoyer temperature/top_p (Mistral), False sinon (modèles
    de raisonnement récents qui refusent ces paramètres).
NB : les IDs de modèles « best » évoluent vite (gpt-5.5, grok-4.3, gemini-2.5-pro,
claude-opus-4-8) — à réviser via les docs fournisseurs si un appel renvoie 404.
"""

import json
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 20000  # audit complet et détaillé (fenêtres modèle ≥ 128k)
# À 20k tokens de sortie la génération peut dépasser 5 min. L'appel tourne en
# thread de fond (UI non bloquée), marge large.
AI_TIMEOUT = 300  # secondes


# ── Registre des fournisseurs ────────────────────────────────────────────────
# key_pref : nom de la préférence (chiffrée) contenant la clé API de ce fournisseur.
PROVIDERS: dict[str, dict] = {
    "anthropic": {
        "label":       "Anthropic (Claude)",
        "api":         "anthropic",
        "model":       "claude-opus-4-8",
        "model_label": "Claude Opus 4.8",
        "key_pref":    "anthropic_api_key",
        "url":         "https://api.anthropic.com/v1/messages",
    },
    "mistral": {
        "label":       "Mistral",
        "api":         "openai",
        "model":       "mistral-large-latest",
        "model_label": "Mistral Large",
        "key_pref":    "mistral_api_key",
        "url":         "https://api.mistral.ai/v1/chat/completions",
        # Mistral accepte les paramètres OpenAI classiques (max_tokens + temperature).
    },
    "openai": {
        "label":            "OpenAI (GPT)",
        "api":              "openai",
        "model":            "gpt-5.5",
        "model_label":      "GPT-5.5",
        "key_pref":         "openai_api_key",
        "url":              "https://api.openai.com/v1/chat/completions",
        "max_tokens_param": "max_completion_tokens",  # série GPT-5 : max_tokens refusé
        "sampling":         False,                    # modèle de raisonnement : pas de temperature
        # gpt-5.5 raisonne en "medium" par défaut → trop lent en non-streaming
        # (dépasse le timeout sur une sortie longue). "low" raisonne encore mais tient
        # le délai ; passer à "medium"/"high" si la profondeur prime sur la latence.
        "extra_params":     {"reasoning_effort": "low"},
        "timeout":          600,                      # marge large (raisonnement + sortie longue)
    },
    "grok": {
        "label":            "Grok (xAI)",
        "api":              "openai",
        "model":            "grok-4.3",
        "model_label":      "Grok 4.3",
        "key_pref":         "grok_api_key",
        "url":              "https://api.x.ai/v1/chat/completions",
        "max_tokens_param": "max_completion_tokens",  # max_tokens déprécié côté xAI
        "sampling":         False,                    # modèle de raisonnement
    },
    "gemini": {
        "label":       "Google (Gemini)",
        "api":         "gemini",
        "model":       "gemini-2.5-pro",
        "model_label": "Gemini 2.5 Pro",
        "key_pref":    "gemini_api_key",
        # {model} est substitué + la clé est ajoutée en ?key= dans _call_gemini.
        "url":         "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    },
}

# Fournisseurs proposés dans l'UI (l'ordre est respecté). Pour en retirer un de la
# liste sans supprimer son support, l'enlever d'ici.
UI_PROVIDERS = ["anthropic", "mistral", "openai", "grok", "gemini"]

DEFAULT_PROVIDER = "anthropic"


def provider_label(provider_id: str) -> str:
    """Libellé lisible d'un fournisseur (fallback sur l'id si inconnu)."""
    p = PROVIDERS.get(provider_id)
    return p["label"] if p else provider_id


def model_label(provider_id: str) -> str:
    """Libellé du modèle utilisé par un fournisseur."""
    p = PROVIDERS.get(provider_id)
    return p["model_label"] if p else "?"


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


def _build_user_prompt(diagnostic_data: dict) -> str:
    """Construit le prompt utilisateur (données + plan d'audit), mutualisé entre fournisseurs."""
    # JSON COMPACT (sans indentation) : l'indentation gonflait le volume de ~50%
    # (169k vs 109k chars) et risquait de tronquer les sections les plus utiles
    # (events/smart). Les modèles parsent le JSON compact sans problème.
    diag_json = json.dumps(diagnostic_data, separators=(",", ":"),
                           ensure_ascii=False, default=str)

    # Filet de sécurité : sur une machine extrêmement chargée en événements, on
    # plafonne pour rester dans la fenêtre contexte. Cas rare avec le compact.
    max_len = 120000
    if len(diag_json) > max_len:
        logger.warning(f"Données diagnostiques tronquées ({len(diag_json)} chars → {max_len})")
        diag_json = diag_json[:max_len] + "\n[… données tronquées …]"

    return f"""Voici le rapport de diagnostic complet d'un poste Windows (généré par Ghisdiag). Analyse les données et produis un audit technique DÉTAILLÉ, actionnable et HONNÊTE : approfondi dans les descriptions et les corrélations, strict sur les preuves.

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


# ── Appels API par famille ────────────────────────────────────────────────────

def _call_openai(provider: dict, api_key: str, user_prompt: str) -> str:
    """Famille OpenAI-compatible (/v1/chat/completions). Couvre Mistral, OpenAI, Grok.

    Paramétrable par fournisseur : nom du champ tokens (max_tokens / max_completion_tokens)
    et envoi ou non des paramètres d'échantillonnage (temperature/top_p).
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": provider["model"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        provider.get("max_tokens_param", "max_tokens"): MAX_OUTPUT_TOKENS,
    }
    # Les modèles de raisonnement récents (GPT-5, Grok 4) refusent temperature/top_p.
    if provider.get("sampling", True):
        payload["temperature"] = 0.2   # faible = réponses factuelles et précises
        payload["top_p"] = 0.9
    # Paramètres spécifiques au fournisseur (ex. reasoning_effort pour GPT-5).
    payload.update(provider.get("extra_params", {}))

    response = requests.post(provider["url"], json=payload, headers=headers, timeout=provider.get("timeout", AI_TIMEOUT))
    _raise_for_status(response, provider)

    data = response.json()
    if not data.get("choices"):
        logger.error(f"Réponse {provider['label']} invalide: {data}")
        raise RuntimeError(f"Format de réponse {provider['label']} invalide")
    return data["choices"][0]["message"]["content"]


def _call_gemini(provider: dict, api_key: str, user_prompt: str) -> str:
    """Famille Google Gemini (generateContent). Clé en ?key=, system_instruction séparé."""
    url = provider["url"].format(model=provider["model"]) + f"?key={api_key}"
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {"maxOutputTokens": MAX_OUTPUT_TOKENS},
    }

    response = requests.post(
        url, json=payload, headers={"Content-Type": "application/json"}, timeout=provider.get("timeout", AI_TIMEOUT)
    )
    _raise_for_status(response, provider)

    data = response.json()
    candidates = data.get("candidates")
    if not candidates:
        # Requête potentiellement bloquée par les filtres de sécurité.
        reason = (data.get("promptFeedback") or {}).get("blockReason")
        logger.error(f"Réponse {provider['label']} sans candidat: {data}")
        raise RuntimeError(
            f"{provider['label']} : réponse vide" + (f" (bloquée : {reason})" if reason else "")
        )
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p)
    if not text:
        logger.error(f"Réponse {provider['label']} sans texte: {data}")
        raise RuntimeError(f"Réponse {provider['label']} vide")
    return text


def _call_anthropic(provider: dict, api_key: str, user_prompt: str) -> str:
    """Famille Anthropic (/v1/messages). `system` séparé, pas de temperature sur Opus 4.x."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload = {
        "model": provider["model"],
        "max_tokens": MAX_OUTPUT_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": user_prompt},
        ],
    }

    response = requests.post(provider["url"], json=payload, headers=headers, timeout=provider.get("timeout", AI_TIMEOUT))
    _raise_for_status(response, provider)

    data = response.json()
    # content est une liste de blocs ; on concatène les blocs de type "text".
    blocks = data.get("content")
    if not isinstance(blocks, list) or not blocks:
        logger.error(f"Réponse {provider['label']} invalide: {data}")
        raise RuntimeError(f"Format de réponse {provider['label']} invalide")
    text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
    if not text:
        logger.error(f"Réponse {provider['label']} sans texte: {data}")
        raise RuntimeError(f"Réponse {provider['label']} vide")
    return text


# Dispatch par famille d'API.
_API_DISPATCH = {
    "openai":    _call_openai,
    "anthropic": _call_anthropic,
    "gemini":    _call_gemini,
}


def _is_invalid_key_400(response) -> bool:
    """Gemini renvoie un 400 (et non 401/403) quand la clé API est invalide."""
    return response.status_code == 400 and (
        "API key not valid" in response.text or "API_KEY_INVALID" in response.text
    )


def _raise_for_status(response, provider: dict):
    """Traduit les codes HTTP courants en exceptions typées (clé invalide vs erreur)."""
    label = provider["label"]
    if response.status_code in (401, 403) or _is_invalid_key_400(response):
        logger.error(f"Erreur authentification {label}: clé API invalide ({response.status_code})")
        raise ValueError(f"Clé API {label} invalide")
    if response.status_code == 429:
        logger.warning(f"Rate limit {label}")
        raise RuntimeError(f"{label} : limite de requêtes atteinte, réessayez dans quelques secondes")
    if response.status_code != 200:
        logger.error(f"Erreur {label} {response.status_code}: {response.text[:500]}")
        raise RuntimeError(f"Erreur {label} : {response.status_code}")


# ── API publique ────────────────────────────────────────────────────────────

def analyze_diagnostic(
    diagnostic_data: dict,
    provider_id: str,
    api_key: str,
    progress_callback: Optional[callable] = None,
) -> Optional[str]:
    """
    Envoie les données diagnostiques au fournisseur IA choisi pour une analyse complète.

    Args:
        diagnostic_data: dict complet retourné par DiagnosticOrchestrator.run()
        provider_id: clé du fournisseur dans PROVIDERS (ex. "anthropic", "mistral")
        api_key: clé API (déchiffrée) du fournisseur
        progress_callback: fonction pour la progression (optionnel)

    Returns:
        Texte de l'analyse (markdown), ou None.

    Raises:
        ValueError: clé API invalide / fournisseur inconnu.
        RuntimeError: erreur réseau, timeout, format de réponse.
    """
    provider = PROVIDERS.get(provider_id)
    if provider is None:
        raise ValueError(f"Fournisseur IA inconnu : {provider_id}")

    label = provider["label"]
    caller = _API_DISPATCH.get(provider["api"])
    if caller is None:
        raise ValueError(f"Famille d'API non implémentée : {provider['api']}")

    try:
        if progress_callback:
            progress_callback(f"Préparation des données pour {label}…")

        user_prompt = _build_user_prompt(diagnostic_data)

        if progress_callback:
            progress_callback(f"Envoi des données à {label}…")

        analysis_text = caller(provider, api_key, user_prompt)

        if progress_callback:
            progress_callback(f"Traitement de la réponse {label}…")

        logger.info(f"Analyse {label} complétée avec succès")
        return analysis_text

    except requests.exceptions.Timeout:
        logger.error(f"Timeout lors de l'appel {label} (>{AI_TIMEOUT}s)")
        raise RuntimeError(f"Timeout {label} — L'analyse a pris trop de temps. Réessayez plus tard.")

    except requests.exceptions.ConnectionError as e:
        logger.error(f"Erreur de connexion {label}: {e}")
        raise RuntimeError(f"Impossible de contacter {label}: {e}")

    except json.JSONDecodeError as e:
        logger.error(f"Erreur parsing JSON {label}: {e}")
        raise RuntimeError(f"Erreur parsing réponse {label}: {e}")

    except (ValueError, RuntimeError):
        # Erreurs déjà typées et formatées : on les laisse remonter telles quelles.
        raise

    except Exception as e:
        logger.exception(f"Erreur inattendue lors de l'analyse {label}")
        raise RuntimeError(f"Erreur analyse {label}: {e}")


def test_api_key(provider_id: str, api_key: str) -> tuple[str, str]:
    """
    Teste rapidement la validité d'une clé API (petit appel).

    Returns:
        (kind, message) où kind ∈ {"ok", "invalid", "error"}.
    """
    provider = PROVIDERS.get(provider_id)
    if provider is None:
        return ("error", f"Fournisseur inconnu : {provider_id}")
    label = provider["label"]

    try:
        if provider["api"] == "anthropic":
            response = requests.post(
                provider["url"],
                json={
                    "model": provider["model"],
                    "max_tokens": 10,
                    "messages": [{"role": "user", "content": "Bonjour"}],
                },
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                timeout=10,
            )
        elif provider["api"] == "gemini":
            url = provider["url"].format(model=provider["model"]) + f"?key={api_key}"
            response = requests.post(
                url,
                json={
                    "contents": [{"role": "user", "parts": [{"text": "Bonjour"}]}],
                    "generationConfig": {"maxOutputTokens": 10},
                },
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
        else:  # openai-compatible (utilise le bon champ tokens, sans sampling)
            response = requests.post(
                provider["url"],
                json={
                    "model": provider["model"],
                    "messages": [{"role": "user", "content": "Bonjour"}],
                    provider.get("max_tokens_param", "max_tokens"): 10,
                },
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=10,
            )

        if response.status_code == 200:
            return ("ok", f"✅  Clé API {label} valide !")
        if response.status_code in (401, 403) or _is_invalid_key_400(response):
            return ("invalid", f"❌  Clé API {label} invalide")
        return ("error", f"Erreur {response.status_code}: {response.text[:200]}")

    except requests.exceptions.Timeout:
        return ("error", f"Timeout — Impossible de contacter {label}")
    except requests.exceptions.ConnectionError:
        return ("error", "Erreur de connexion")
    except Exception as e:
        return ("error", f"Erreur: {e}")
