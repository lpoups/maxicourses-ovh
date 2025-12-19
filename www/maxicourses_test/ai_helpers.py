"""AI helpers for smart Leclerc searches.

This module centralises every interaction with the LLM used to generate search
queries and to validate the cards returned by Leclerc Drive.  Each helper
returns a structured ``AIResponse`` that contains both the parsed data and the
raw prompt/response so the caller can persist them in ``logs/refonte_v2``.

When the environment variable ``USE_AI_ASSIST`` is absent or evaluates to false
({"0", "false", "no"}), all helpers immediately degrade to a deterministic
behaviour that preserves the current pipeline logic.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
import unicodedata
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:  # Python ≥ 3.11
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback for older interpreters
    import tomli as tomllib  # type: ignore

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------
USE_AI_ASSIST = os.getenv("USE_AI_ASSIST", "false").lower() in {"1", "true", "yes"}

_CONFIG_CACHE: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _http_post(
    url: str,
    *,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout: float,
) -> Tuple[int, str]:
    """Minimal JSON POST helper relying only on the standard library."""

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.getcode()
            body = response.read().decode("utf-8")
            return status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, body
# ---------------------------------------------------------------------------
# Keyword generation helpers
# ---------------------------------------------------------------------------

_PRIMARY_FORBIDDEN = {
    "promo",
    "promotion",
    "lot",
    "lots",
    "pack",
    "packs",
    "x2",
    "x3",
    "x4",
    "x6",
    "offre",
    "offres",
    "produit",
    "produits",
    "au",
    "aux",
    "de",
    "du",
    "des",
    "d",
    "l",
    "le",
    "la",
    "les",
    "adulte",
    "adultes",
    "adolescent",
    "adolescents",
    "stérilisé",
    "stérilisée",
    "stérilisés",
    "stérilisées",
    "sterilise",
    "sterilisee",
    "sterilises",
    "sterilisees",
    "senior",
    "seniors",
    "filiation",
    "course",
}

_ANIMAL_TOKENS = {"chat", "chats", "chien", "chiens"}
_PET_FOOD_FORMS = {"croquettes", "croquette", "pâtée", "patee", "patée"}
_PET_FOOD_VARIANTS = {
    "saumon",
    "poulet",
    "boeuf",
    "bœuf",
    "dinde",
    "thon",
    "ble",
    "blé",
    "legumes",
    "légumes",
}

_LAUNDRY_TERMS = {"lessive", "lessives"}
_LAUNDRY_FORMS = {"capsules", "capsule", "liquide", "poudre", "tablettes", "tablette"}
_LAUNDRY_VARIANTS = {"grandiose", "original", "anti-odeur", "parfum", "fraîcheur", "fraicheur"}

_CONDIMENT_TYPES = {"moutarde", "ketchup", "sauce", "mayonnaise", "condiment"}
_CONDIMENT_VARIANTS = {"aromates", "douce", "forte", "ancienne", "miel"}

_SECONDARY_STOPWORDS = {
    "kg",
    "g",
    "l",
    "ml",
    "cl",
    "pour",
    "et",
    "au",
    "aux",
    "la",
    "le",
    "les",
    "des",
    "du",
    "de",
    "d",
    "u",
    "avec",
    "sans",
    "ultima",
    "amora",
    "capsules",
    "capsule",
    "lessive",
    "en",
    "pot",
    "marque",
    "conditionnee",
    "conditionnees",
    "conditionnee",
    "conditionnees"
}


def _normalize_brand_display(value: str) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"\s+", " ", value.strip())
    if not cleaned:
        return ""
    if cleaned.isupper() and any(ch in cleaned for ch in "- "):
        return cleaned.title()
    return cleaned


def _split_tokens(value: Optional[str]) -> List[str]:
    if not isinstance(value, str):
        return []
    tokens = re.split(r"[^0-9a-zA-ZÀ-ÖØ-öø-ÿ]+", value.strip())
    return [tok for tok in tokens if tok]


def _strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", value) if unicodedata.category(ch) != "Mn"
    )


def _normalize_token(value: str) -> str:
    value = _strip_accents(value.lower())
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def _normalize_quantity(quantity: Optional[str]) -> Optional[str]:
    if not quantity:
        return None
    q = quantity.strip().lower()
    q = q.replace(",", ".")
    q = q.replace(",", ".").replace(" ", "")
    q = re.sub(r"\s+", " ", q)
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(kg|g|l|ml|cl|capsule|capsules|unité|unités|u|pcs)", q)
    if match:
        try:
            value_float = float(match.group(1))
        except (ValueError, TypeError):
            return None
        value, unit = match.groups()
        unit = unit.replace("unité", "u").replace("unités", "u")
        if unit in {"capsule", "capsules"}:
            unit = "capsules"
        if unit == "g" and float(value) >= 1000:
            value = f"{float(value) / 1000:.1f}"
            unit = "kg"
        if unit == "ml" and float(value) >= 1000:
            value = f"{float(value) / 1000:.1f}"
            unit = "l"
        value = value.rstrip("0").rstrip(".") if "." in value else value
        if unit in {"capsules", "pcs", "u"}:
            unit_display = "capsules" if unit == "capsules" else unit
            return f"{value} {unit_display}".strip()
        return f"{value}{unit}"
    q = q.replace(" ", "")
    if q:
        return q
    return None


def _normalize_volume(quantity: Optional[str]) -> Tuple[Optional[str], List[str]]:
    """Return canonical volume (e.g. '1,75L') and variants (['1,75', '1.75', '175'])."""
    if not isinstance(quantity, str):
        return None, []
    raw = quantity.strip()
    if not raw:
        return None, []
    normalized = raw.lower()
    normalized = normalized.replace("litres", "l").replace("litre", "l")
    normalized = normalized.replace(" ", "")
    match = re.match(r"([0-9]+(?:[\\.,][0-9]+)?)(?:([a-z]+))?", normalized)
    if not match:
        return raw.strip(), [raw.strip()]
    value_str, unit = match.groups()
    unit = (unit or "").lower()
    try:
        numeric = float(value_str.replace(",", "."))
    except ValueError:
        numeric = None
    canonical_unit = unit.upper() if unit else ""
    canonical_value = value_str.replace(".", ",")
    canonical = f"{canonical_value}{canonical_unit}" if canonical_unit else canonical_value
    variants: List[str] = []
    variants.append(canonical)
    variants.append(canonical_value)
    variants.append(canonical_value.replace(",", "."))
    if numeric is not None and unit in {"l", "cl", "ml"}:
        if unit == "l":
            centiliters = f"{int(round(numeric * 100)):d}"
            variants.append(centiliters)
            variants.append(f"{centiliters}cl")
        elif unit == "cl":
            liters = numeric / 100.0
            variants.append(f"{liters:.2f}".rstrip("0").rstrip("."))
            variants.append(f"{liters:.2f}".rstrip("0").rstrip(".") + "L")
        elif unit == "ml":
            liters = numeric / 1000.0
            variants.append(f"{liters:.2f}".rstrip("0").rstrip("."))
            variants.append(f"{liters:.2f}".rstrip("0").rstrip(".") + "L")
    variants_clean = []
    for item in variants:
        item_clean = item.strip()
        if item_clean and item_clean not in variants_clean:
            variants_clean.append(item_clean)
    return canonical, variants_clean


def _extract_tokens(*values: Optional[str]) -> List[str]:
    tokens: List[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        for token in re.findall(r"[0-9a-zA-ZÀ-ÖØ-öø-ÿ']+", value):
            tok_norm = _normalize_token(token)
            if not tok_norm:
                continue
            if tok_norm in seen:
                continue
            seen.add(tok_norm)
            tokens.append(token.lower())
    return tokens


def _detect_category(tokens: List[str]) -> str:
    normalized = {_normalize_token(tok) for tok in tokens}
    if normalized & { _normalize_token(t) for t in _PET_FOOD_FORMS }:
        return "pet_food"
    if normalized & { _normalize_token(t) for t in _LAUNDRY_TERMS }:
        return "laundry"
    if normalized & { _normalize_token(t) for t in _CONDIMENT_TYPES }:
        return "condiment"
    return "generic"


def _build_primary_secondary(profile: Dict[str, Any], descriptor: Dict[str, Any]) -> Dict[str, Any]:
    brand_raw = (profile.get("brand") or descriptor.get("brand") or "").strip()
    brand = _normalize_brand_display(brand_raw) or brand_raw
    quantity = _normalize_quantity(profile.get("quantity") or descriptor.get("quantity"))
    name = profile.get("name") or descriptor.get("name") or ""
    description = profile.get("description") or descriptor.get("description") or ""
    quantity_raw = profile.get("quantity") or descriptor.get("seed_primary_quantity") or descriptor.get("quantity")
    canonical_volume, volume_variants = _normalize_volume(quantity_raw)

    brand_tokens = [_normalize_brand_display(tok) for tok in _split_tokens(brand)]
    brand_tokens = [tok for tok in brand_tokens if tok]

    variant_sources = [
        descriptor.get("seed_primary_name"),
        descriptor.get("name"),
        descriptor.get("description"),
    ]
    variant_stopwords = {
        "boisson",
        "boissons",
        "soda",
        "gazeuse",
        "gazeux",
        "format",
        "bouteille",
        "bouteilles",
        "pack",
        "lot",
        "mini",
        "parfum",
        "saveur",
        "produit",
        "produits",
    }
    variant_tokens: List[str] = []
    for source in variant_sources:
        for token in _split_tokens(source):
            norm = _normalize_token(token)
            if not norm or norm in _PRIMARY_FORBIDDEN or norm in variant_stopwords:
                continue
            if any(_normalize_token(bt) == norm for bt in brand_tokens):
                continue
            if token.lower() not in (tok.lower() for tok in variant_tokens):
                variant_tokens.append(token.lower())

    # Prioritise variants that add information (ex: "original", "grandiose")
    if not variant_tokens:
        # fallback to category token (pet food, etc.)
        tokens = _extract_tokens(name, description)
        for token in tokens:
            norm = _normalize_token(token)
            if norm in variant_stopwords:
                continue
            if any(_normalize_token(bt) == norm for bt in brand_tokens):
                continue
            if token.lower() not in (tok.lower() for tok in variant_tokens):
                variant_tokens.append(token.lower())

    def make_query(parts: List[str]) -> Optional[str]:
        candidate = " ".join([part for part in parts if part])
        candidate = re.sub(r"\s+", " ", candidate).strip()
        candidate = candidate.replace(" ,", ",").replace(" .", ".")
        candidate = candidate.replace(" l", " L")
        if len(candidate) > 30:
            candidate = candidate[:30].rstrip()
        return candidate if candidate else None

    primary_candidates: List[str] = []

    def add_primary(parts: List[str]) -> None:
        candidate = make_query(parts)
        if not candidate:
            return
        if candidate.lower() in (item.lower() for item in primary_candidates):
            return
        primary_candidates.append(candidate)

    if brand:
        add_primary([brand])
    if brand and canonical_volume:
        add_primary([brand, canonical_volume])
    if brand and variant_tokens:
        add_primary([brand, variant_tokens[0]])
    if brand and canonical_volume and variant_tokens:
        add_primary([brand, variant_tokens[0], canonical_volume])
    if brand and len(variant_tokens) >= 2:
        add_primary([brand, variant_tokens[0], variant_tokens[1]])
    if brand and volume_variants:
        for volume_alt in volume_variants:
            add_primary([brand, volume_alt])
            if variant_tokens:
                add_primary([brand, volume_alt, variant_tokens[0]])
            if len(primary_candidates) >= 5:
                break

    primary_clean = primary_candidates[:5]

    secondary_tokens: List[str] = []
    for token in brand_tokens:
        token_clean = token.lower()
        if token_clean not in secondary_tokens:
            secondary_tokens.append(token_clean)
    for token in variant_tokens:
        token_clean = token.lower()
        if token_clean not in secondary_tokens:
            secondary_tokens.append(token_clean)
    for volume in volume_variants:
        vol_clean = volume.lower()
        if vol_clean not in secondary_tokens:
            secondary_tokens.append(vol_clean)

    return {
        "category": _detect_category(_extract_tokens(name, description)),
        "primary": primary_clean,
        "secondary": secondary_tokens,
    }


def _enforce_query_rules(
    profile: Dict[str, Any],
    descriptor: Dict[str, Any],
    queries: List[str],
) -> Dict[str, Any]:
    """Clean and prioritize queries without over-engineering token shuffling."""
    
    # Extract clean brand/quantity
    brand_raw = profile.get("brand") or descriptor.get("brand") or ""
    brand = _normalize_brand_display(brand_raw)
    
    # 1. Clean the AI provided queries
    cleaned_queries: List[str] = []
    seen: set[str] = set()
    
    for q in queries:
        # Normalize spaces
        q_clean = " ".join(q.split()).strip()
        
        # Remove dumb repetition ("Studio Studio")
        tokens = q_clean.split()
        deduped_tokens = []
        prev_token = ""
        for t in tokens:
            if t.lower() != prev_token.lower():
                deduped_tokens.append(t)
            prev_token = t
        q_clean = " ".join(deduped_tokens)
        
        if len(q_clean) > 40: # Allow slightly longer for specific products
             q_clean = q_clean[:40].rsplit(' ', 1)[0] # Cut at last space
             
        if q_clean and q_clean.lower() not in seen:
            cleaned_queries.append(q_clean)
            seen.add(q_clean.lower())

    # 2. Generate a strict fallback "Brand + 2 words of Name"
    # This ensures we always have a safe, generated query if AI goes weird
    name_parts = _split_tokens(profile.get("name") or descriptor.get("name") or "")
    safe_tokens = [t for t in name_parts if t.lower() not in _PRIMARY_FORBIDDEN][:2]
    if brand and safe_tokens:
        fallback = f"{brand} {' '.join(safe_tokens)}"
        if fallback.lower() not in seen:
            cleaned_queries.insert(0, fallback) # Put as second option (AI is first)
            seen.add(fallback.lower())

    return {
        "primary": cleaned_queries[:4], # Keep top 4
        "secondary": cleaned_queries[4:], # Rest
        "category": "generic", # Simplified
    }


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _config_path() -> Path:
    return Path(__file__).resolve().with_name("ai_helpers.toml")


def _load_config() -> Dict[str, Any]:
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE
    path = _config_path()
    if not path.exists():
        _CONFIG_CACHE = {}
        return _CONFIG_CACHE
    try:
        _CONFIG_CACHE = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _CONFIG_CACHE = {}
    return _CONFIG_CACHE


def _openai_settings() -> Dict[str, Any]:
    config = _load_config()
    return config.get("openai", {}) if isinstance(config, dict) else {}
    return config.get("openai", {}) if isinstance(config, dict) else {} # Keep for backward compatibility

def _gemini_settings() -> Dict[str, Any]:
    config = _load_config()
    return config.get("gemini", {}) if isinstance(config, dict) else {}


def _resolve_api_key(settings: Dict[str, Any]) -> Optional[str]:
    key = os.getenv("OPENAI_API_KEY")
    key = os.getenv("OPENAI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if key:
        return key.strip()
    candidate = settings.get("api_key") if isinstance(settings, dict) else None
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    return None


# ---------------------------------------------------------------------------
# Response container
# ---------------------------------------------------------------------------

@dataclass
class AIResponse:
    """Container returned by helper functions for easier logging downstream."""

    status: str
    data: Dict[str, Any]
    raw_prompt: Optional[str] = None
    raw_response: Optional[str] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Low-level OpenAI call
# ---------------------------------------------------------------------------

def _call_openai(
    *,
    model: str,
    messages: List[Dict[str, str]],
    response_format: Optional[str] = "json_object",
    temperature: float = 0.2,
) -> Dict[str, Any]:
    """Low-level OpenAI call with graceful fallback.

    Tries the configured model first; if it fails with a model-not-found (404)
    or rate-limit (429), it retries with known stable fallbacks
    (gpt-4o, gpt-4o-mini) without crashing the pipeline.
    """

    settings = _openai_settings()
    # Prioritize Gemini if configured, otherwise fallback to OpenAI
    gemini_settings = _gemini_settings()
    openai_settings = _openai_settings()
    
    is_gemini = "gemini" in model.lower() or (gemini_settings and not openai_settings)
    settings = gemini_settings if is_gemini else openai_settings

    api_key = _resolve_api_key(settings)
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY (env or ai_helpers.toml)")
        raise RuntimeError("Missing API Key (GEMINI_API_KEY or OPENAI_API_KEY in env or ai_helpers.toml)")

    base_url = settings.get("base_url") or "https://api.openai.com/v1"
    endpoint = settings.get("endpoint") or "chat/completions"
    base_url = settings.get("base_url") or ("https://generativelanguage.googleapis.com/v1beta" if is_gemini else "https://api.openai.com/v1")
    endpoint = settings.get("endpoint") or (f"models/{model}:generateContent" if is_gemini else "chat/completions")
    url_param_sep = "?" if is_gemini else ""
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}{url_param_sep}{'key=' + api_key if is_gemini else ''}"

    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"

    def make_payload(model_name: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        elif response_format:
            payload["response_format"] = response_format
        return payload

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if not is_gemini:
        headers["Authorization"] = f"Bearer {api_key}"

    fallbacks = settings.get("fallback_models") or ["gpt-4o", "gpt-4o-mini"]
    timeout = float(settings.get("timeout_seconds") or 90)
    tried: List[str] = []
    for candidate in [model] + [m for m in fallbacks if m != model]:
        tried.append(candidate)
        try:
            status, body = _http_post(
                url,
                headers=headers,
                payload=make_payload(candidate),
                timeout=timeout,
            )
        except urllib.error.URLError:
            continue
        except Exception:
            continue
        if status == 200:
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                continue
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {}
        err = parsed.get("error") if isinstance(parsed, dict) else {}
        if not isinstance(err, dict):
            err = {}
        code = err.get("code") if isinstance(err, dict) else None
        if status in (404, 429) or code in {"model_not_found", "rate_limit_exceeded"}:
            continue
        if status >= 400:
            snippet = body.strip().replace("\n", " ")
            snippet = snippet[:200]
            raise RuntimeError(f"OpenAI HTTP {status}: {snippet}")

    # If we reach here, everything failed – raise a generic error
    raise RuntimeError(f"OpenAI call failed for models: {', '.join(tried)}")


def _extract_json_content(response: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return {}
    message = choices[0].get("message", {})
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        content = content.strip()
        if not content:
            return {}
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            snippet = content[start : end + 1]
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                return {}
    return {}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def summarize_product_seed(
    seed_payloads: Iterable[Dict[str, Any]],
    *,
    context: Optional[Dict[str, Any]] = None,
) -> AIResponse:
    """Return an AI product profile derived from the seed payloads."""

    if not USE_AI_ASSIST:
        return AIResponse(status="disabled", data={"profile": None, "keywords": []})

    settings = _openai_settings()
    model = settings.get("model_profile") or settings.get("model_queries")
    if not model:
        return AIResponse(
            status="error",
            data={"profile": None, "keywords": []},
            error="Missing model_profile in ai_helpers.toml",
        )

    payload_list = [payload for payload in seed_payloads if isinstance(payload, dict)]
    user_payload = {
        "seeds": payload_list,
        "context": context or {},
    }
    prompt = json.dumps(user_payload, ensure_ascii=False, indent=2)

    messages = [
        {
            "role": "system",
            "content": (
                "Tu es un expert en e-commerce. Ta mission est de générer des mots-clés de recherche PRÉCIS pour retrouver un produit en supermarché Drive."
                "Analyzes les données 'seeds' fournies (titre, marque, description)."
                "\n"
                "RÈGLES DE GÉNÉRATION :"
                "1. Retourne JSON strict avec clés: 'profile' (obj) et 'keywords' (list[str])."
                "2. 'profile': Extrais {brand: str, name: str, quantity: str} proprement."
                "3. 'keywords': Génère 3 à 5 variantes de recherche MAXimum."
                "4. FORMAT MOT-CLÉ: Toujours 'Marque + Produit + Poids/Vol'."
                "   - Ex: 'Nutella Pâte à tartiner 400g'"
                "   - Ex: 'Coca-Cola Soda 1.75L'"
                "   - Ex: 'Le Chat Lessive Capsules x32'"
                "5. INTERDIT: Ne répète PAS les mots (pas de 'Studio Studio'). Pas de mots génériques seuls ('Promotion', 'Lot')."
                "6. NETTOYAGE: Supprime les caractères superflus, mets les marques en premier."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    try:
        response = _call_openai(model=model, messages=messages)
    except Exception as exc:  # pragma: no cover - network/runtime errors
        return AIResponse(
            status="error",
            data={"profile": None, "keywords": []},
            raw_prompt=prompt,
            error=str(exc),
        )

    data = _extract_json_content(response)
    profile = data.get("profile") if isinstance(data, dict) else None
    keywords = data.get("keywords") if isinstance(data, dict) else None
    if not isinstance(keywords, list):
        keywords = []
    cleaned_keywords: List[str] = []
    for item in keywords:
        if isinstance(item, str):
            value = " ".join(item.split())
            if value and value not in cleaned_keywords:
                if len(value) > 30:
                    value = value[:30].rstrip()
                cleaned_keywords.append(value)

    normalized_profile = None
    if isinstance(profile, dict):
        normalized_profile = dict(profile)
        brand_value = normalized_profile.get("brand")
        if isinstance(brand_value, str):
            brand_normalized = _normalize_brand_display(brand_value) or brand_value.strip()
            if brand_normalized:
                normalized_profile["brand"] = brand_normalized
        profile = normalized_profile

    descriptor_context = {}
    if isinstance(context, dict):
        descriptor_context = context.get("descriptor") or {}
        if not isinstance(descriptor_context, dict):
            descriptor_context = {}
    keyword_info = _enforce_query_rules(profile or {}, descriptor_context, cleaned_keywords)

    result_payload = {
        "profile": profile if isinstance(profile, dict) else None,
        "keywords": cleaned_keywords,
        "primary_keywords": keyword_info.get("primary", []),
        "secondary_keywords": keyword_info.get("secondary", []),
        "category": keyword_info.get("category"),
        "raw": data,
    }
    return AIResponse(
        status="ok",
        data=result_payload,
        raw_prompt=prompt,
        raw_response=json.dumps(response, ensure_ascii=False),
    )


def compute_vision_similarity(
    img1_b64: str,
    img2_b64: str,
) -> AIResponse:
    """Compare two Base64-encoded images using a Vision model (OpenAI-compatible)."""

    if not USE_AI_ASSIST:
        return AIResponse(status="disabled", data={"match": False, "confidence": 0.0})

    settings = _openai_settings()
    # Use gpt-4o by default for vision as it is most capable
    model = settings.get("model_vision", "gpt-4o")

    # Construct messages with image_url payload (Base64)
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert product matcher for a supermarket."
                " Compare the two images provided."
                " Determine if they represent the EXACT same product variant (brand, product name, quantity)."
                " Ignore minor packaging updates or lighting differences."
                " Return JSON: {match: boolean, confidence: float, reason: string}."
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Are these products identical?"},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img1_b64}" if not img1_b64.startswith("data:") else img1_b64}
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img2_b64}" if not img2_b64.startswith("data:") else img2_b64}
                },
            ],
        },
    ]

    try:
        response = _call_openai(model=model, messages=messages, temperature=0.0)
    except Exception as exc:
        return AIResponse(
            status="error",
            data={"match": False, "confidence": 0.0, "reason": "api_error"},
            error=str(exc),
        )

    data = _extract_json_content(response)
    return AIResponse(
        status="ok",
        data=data,
        raw_response=json.dumps(response, ensure_ascii=False),
    )


def suggest_search_queries(
    ai_profile: Dict[str, Any],
    *,
    descriptor: Optional[Dict[str, Any]] = None,
    max_queries: int = 5,
    store: str = "leclerc",
    max_length: int = 30,
) -> AIResponse:
    """Return a ranked list of search queries tailored for a text-only store."""

    if not USE_AI_ASSIST:
        return AIResponse(status="disabled", data={"queries": []})

    settings = _openai_settings()
    model = settings.get("model_queries") or settings.get("model_profile")
    if not model:
        return AIResponse(
            status="error",
            data={"queries": []},
            error="Missing model_queries in ai_helpers.toml",
        )

    payload = {
        "profile": ai_profile or {},
        "descriptor": descriptor or {},
        "store": store,
        "constraints": {
            "max_queries": max_queries,
            "max_length": max_length,
        },
    }
    prompt = json.dumps(payload, ensure_ascii=False, indent=2)

    messages = [
        {
            "role": "system",
            "content": (
                f"You are a Search Query Specialist for the French grocery store {store}. "
                "Your goal is to generate 3 tailored search queries to find the product described in the JSON payload.\n"
                "Return a strict JSON object with these keys:\n"
                "- 'golden': The ideal specific query (Brand + Product + important variant). Max 3-4 words.\n"
                "- 'fallback_specific': A specific alternative (e.g. without Brand if generic, or different word order).\n"
                "- 'fallback_broad': A broader query (Brand + Category or Product + Category) to ensure results.\n"
                f"Constraints:\n"
                f"- Max length per query: {max_length} chars.\n"
                "- NO generic terms like 'produit', 'promo', 'achat'.\n"
                "- NO punctuation like dots or quotes unless part of the brand.\n"
                f"- For store '{store}', adapt to its search engine quirks (e.g. Leclerc dislikes complex brand names).\n"
                "- If store is 'monoprix':\n"
                "  - ALWAYS use lowercase.\n"
                "  - ALWAYS include unit quantities like '6x33cl' or '6x1l'.\n"
                "  - DO NOT include standalone weight/volume like '500g' or '1.5l' unless it is a unit quantity.\n"
                "  - DO NOT use spaces in quantities (e.g. use '500g' not '500 g').\n"
                "Output JSON ONLY."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    try:
        response = _call_openai(model=model, messages=messages)
    except Exception as exc:  # pragma: no cover
        return AIResponse(
            status="error",
            data={"queries": []},
            raw_prompt=prompt,
            error=str(exc),
        )

    data = _extract_json_content(response)
    
    # Parse the structured response
    golden = data.get("golden")
    fallback_specific = data.get("fallback_specific")
    fallback_broad = data.get("fallback_broad")
    
    # Also support legacy 'queries' list if the model hallucinates the old format
    legacy_list = data.get("queries", []) if isinstance(data.get("queries"), list) else []

    # Construct the prioritized list
    final_queries: List[str] = []
    
    def add_q(q):
        if not isinstance(q, str): return
        val = " ".join(q.split())
        if val and len(val) <= max_length and val not in final_queries:
            final_queries.append(val)

    add_q(golden)
    add_q(fallback_specific)
    add_q(fallback_broad)
    for q in legacy_list:
        add_q(q)
        if len(final_queries) >= max_queries:
            break

    keyword_info = _enforce_query_rules(ai_profile or {}, descriptor or {}, final_queries)

    return AIResponse(
        status="ok",
        data={
            "queries": keyword_info.get("primary", []),
            "secondary_keywords": keyword_info.get("secondary", []),
            "category": keyword_info.get("category"),
            "structured": {
                "golden": golden,
                "fallback_specific": fallback_specific,
                "fallback_broad": fallback_broad
            },
            "raw": data,
        },
        raw_prompt=prompt,
        raw_response=json.dumps(response, ensure_ascii=False),
    )


def score_leclerc_candidates(
    ai_profile: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    *,
    query: Optional[str] = None,
) -> AIResponse:
    """Score each Leclerc search candidate (MATCH / NO_MATCH)."""

    if not USE_AI_ASSIST:
        verdicts = [
            {
                "status": "NO_MATCH",
                "score": 0.0,
                "justification": "AI assist disabled",
            }
            for _ in candidates
        ]
        return AIResponse(status="disabled", data={"verdicts": verdicts})

    settings = _openai_settings()
    model = settings.get("model_validation") or settings.get("model_queries")
    if not model:
        return AIResponse(
            status="error",
            data={"verdicts": []},
            error="Missing model_validation in ai_helpers.toml",
        )

    payload = {
        "profile": ai_profile or {},
        "query_used": query,
        "candidates": candidates,
    }
    prompt = json.dumps(payload, ensure_ascii=False, indent=2)

    messages = [
        {
            "role": "system",
            "content": (
                "Analyse les résultats Leclerc Drive et décide si chaque carte"
                " correspond exactement au produit recherché. Réponds avec un JSON :"
                " verdicts (liste) où chaque entrée possède les clés status"
                " (MATCH|EQUIVALENT|NO_MATCH), score (0-1), justification et"
                " difference_note lorsque le statut vaut EQUIVALENT. Ajoute"
                " optionnellement recommended_index (entier) pour signaler la carte"
                " à ouvrir si différente de celle actuelle. Utilise MATCH"
                " uniquement pour une correspondance parfaite (EAN, format, parfum,"
                " quantité, marque). Utilise EQUIVALENT lorsqu'il s'agit d'un"
                " substitut pertinent mais différent et explique la différence"
                " (format, parfum, pack…). Si aucune carte n'est acceptable,"
                " retourne NO_MATCH : l'application n'affiche alors rien."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    try:
        response = _call_openai(model=model, messages=messages)
    except Exception as exc:  # pragma: no cover
        return AIResponse(
            status="error",
            data={"verdicts": []},
            raw_prompt=prompt,
            error=str(exc),
        )

    data = _extract_json_content(response)
    verdicts = data.get("verdicts") if isinstance(data, dict) else None
    if not isinstance(verdicts, list):
        verdicts = []
    cleaned: List[Dict[str, Any]] = []
    for verdict in verdicts:
        if not isinstance(verdict, dict):
            continue
        status = verdict.get("status")
        if status not in {"MATCH", "NO_MATCH", "EQUIVALENT"}:
            continue
        score = verdict.get("score")
        try:
            score_value = float(score)
        except (TypeError, ValueError):
            score_value = 0.0
        difference_note = verdict.get("difference_note")
        if isinstance(difference_note, str):
            difference_note = difference_note.strip()
        else:
            difference_note = None
        cleaned.append(
            {
                "status": status,
                "score": max(0.0, min(score_value, 1.0)),
                "justification": verdict.get("justification", ""),
                "recommended_index": verdict.get("recommended_index"),
                "difference_note": difference_note,
            }
        )

    return AIResponse(
        status="ok",
        data={"verdicts": cleaned, "raw": data},
        raw_prompt=prompt,
        raw_response=json.dumps(response, ensure_ascii=False),
    )


def suggest_equivalent(
    ai_profile: Dict[str, Any],
    candidates: List[Dict[str, Any]],
) -> AIResponse:
    """Optionally suggest an equivalent product when the exact one is absent."""

    if not USE_AI_ASSIST:
        return AIResponse(status="disabled", data={"equivalent": None})

    settings = _openai_settings()
    model = settings.get("model_equivalent") or settings.get("model_validation")
    if not model:
        return AIResponse(
            status="error",
            data={"equivalent": None},
            error="Missing model_equivalent in ai_helpers.toml",
        )

    payload = {
        "profile": ai_profile or {},
        "candidates": candidates,
    }
    prompt = json.dumps(payload, ensure_ascii=False, indent=2)

    messages = [
        {
            "role": "system",
            "content": (
                "Si aucune carte ne correspond exactement, propose un produit"
                " équivalent pertinent. Réponds avec un JSON possédant la clé"
                " equivalent (objet ou null) avec les attributs title et reason."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    try:
        response = _call_openai(model=model, messages=messages)
    except Exception as exc:  # pragma: no cover
        return AIResponse(
            status="error",
            data={"equivalent": None},
            raw_prompt=prompt,
            error=str(exc),
        )

    data = _extract_json_content(response)
    equivalent = data.get("equivalent") if isinstance(data, dict) else None
    if not isinstance(equivalent, dict):
        equivalent = None

    return AIResponse(
        status="ok",
        data={"equivalent": equivalent, "raw": data},
        raw_prompt=prompt,
        raw_response=json.dumps(response, ensure_ascii=False),
    )
