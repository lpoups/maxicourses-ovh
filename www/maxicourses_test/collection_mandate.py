"""Centralised methodology mandate for price collection scripts.

This module is *the* reference embedded in the codebase that reminds every
future automation agent of the contractual workflow agreed with Laurent.
Do not remove or alter the intent without his explicit approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Tuple

MANDATE_VERSION = "2024-09-26T00:00Z"

AUTHORITY_STATEMENT = (
    "Laurent (humain) conçoit, décide et valide. Les assistants GPT exécutent la\n"
    "récolte de prix sans initiative non validée. Poser des questions est\n"
    "possible, désobéir est interdit."
)

GLOBAL_IMPERATIVES: Tuple[str, ...] = (
    "Chrome remote obligatoire via start_chrome_debug.sh (profil .chrome-debug) puis USE_CDP=1, HEADLESS=0 pour les validations.",
    "Avant toute collecte, récupérer un descriptif seed : Carrefour City en priorité, puis Auchan si l'EAN est absent.",
    "Chaque JSON résultat doit exposer prix TTC, prix unitaire (€/kg ou €/L), quantité, magasin, horodatage UTC, URL, matched_ean.",
    "Aucune donnée saisie manuellement : tous les prix proviennent des scripts Playwright/CDP.",
    "Image locale obligatoire dans pipeline/assets et lien ‘Voir image’ actif dans pipeline/index2.html.",
    "MAJ systématique de docs/HANDOVER_DAILY.md en fin de session avec traces et commandes clés.",
)


@dataclass(frozen=True)
class MethodSpec:
    key: str
    enseigne: str
    script: str
    summary: str
    store_hint: str
    trace_files: Tuple[str, ...]
    steps: Tuple[str, ...]
    outputs: Tuple[str, ...]
    notes: Tuple[str, ...]


METHODS: Dict[str, MethodSpec] = {
    "leclerc_drive": MethodSpec(
        key="leclerc_drive",
        enseigne="Leclerc Drive Bruges",
        script="manual_leclerc_cdp.py / fetch_leclerc_drive_price.py",
        summary=(
            "Rejoue la navigation humaine sur fd12-courses.leclercdrive.fr,"
            " saisit la requête lentement, ouvre la fiche la plus pertinente et"
            " extrait prix + prix/L."
        ),
        store_hint="Drive Bruges (magasin-173301)",
        trace_files=("leclerc-20250924-drive-select.jsonl",),
        steps=(
            "Lancer start_chrome_debug.sh puis vérifier le port 9222.",
            "Exécuter manual_leclerc_cdp.py avec delays humains (env LECLERC_*).",
            "Valider que le magasin affiché reste Bruges avant la recherche.",
            "Utiliser le descriptif seed pour choisir la carte produit (tokens libellé).",
            "Sauvegarder capture PDP pour docs/HANDOVER_DAILY.md.",
        ),
        outputs=(
            "results/test-<EAN>/latest.json",
            "results/test-<EAN>/summary.json",
            "results/summary.json",
        ),
        notes=(
            "OneTrust à accepter si présent, attendre 5-12 s entre actions pour rester humain.",
            "Ne jamais changer le script Leclerc stable : toute évolution passe par nouvelle trace.",
        ),
    ),
    "carrefour_city": MethodSpec(
        key="carrefour_city",
        enseigne="Carrefour City Bordeaux Balguerie",
        script="fetch_carrefour_price_city.py",
        summary=(
            "Rejoue la trace city (carrefour-switch-back-20250923.jsonl) afin de"
            " verrouiller le magasin City avant de lancer fetch_carrefour_price.py."
        ),
        store_hint="City Bordeaux Balguerie",
        trace_files=("carrefour-switch-back-20250923.jsonl",),
        steps=(
            "start_chrome_debug.sh, USE_CDP=1, HEADLESS=0 pour vérif.",
            "Relancer la trace city si la bannière ne montre pas Carrefour City.",
            "Passer la requête seed (libellé seed) via fetch_carrefour_price.py.",
            "Contrôler que le JSON store mentionne bien 'City'.",
        ),
        outputs=(
            "results/test-<EAN>/latest.json",
            "results/test-<EAN>/summary.json",
        ),
        notes=(
            "Market et City sont traités comme deux enseignes distinctes.",
            "Si City n'a pas le produit, fallback seed Auchan avant les autres enseignes.",
        ),
    ),
    "carrefour_market": MethodSpec(
        key="carrefour_market",
        enseigne="Carrefour Market Bordeaux Fondaudège",
        script="fetch_carrefour_price_market.py",
        summary=(
            "Rejoue la trace market (carrefour-store-switch-20250923.jsonl) pour"
            " s'assurer que le drive actif est le Market avant extraction."
        ),
        store_hint="Market Fondaudège",
        trace_files=("carrefour-store-switch-20250923.jsonl",),
        steps=(
            "Toujours exécuter fetch_carrefour_price_city.py en premier pour le seed.",
            "Ensuite seulement lancer le wrapper Market (trace + fetch).",
            "Vérifier que le JSON store contient 'Market' et que le prix diffère du City.",
        ),
        outputs=(
            "results/test-<EAN>/latest.json",
            "results/test-<EAN>/summary.json",
        ),
        notes=(
            "Si City et Market renvoient le même prix => bug : revalider les traces.",
            "Ne jamais mélanger les traces : un fichier par enseigne.",
        ),
    ),
    "auchan": MethodSpec(
        key="auchan",
        enseigne="Auchan Mériadeck",
        script="fetch_auchan_price.py",
        summary="Utilise state/auchan.json et la trace auchan-20240922-clean.jsonl pour charger le magasin Bordeaux Mériadeck.",
        store_hint="Auchan Bordeaux Mériadeck",
        trace_files=("auchan-20240922-clean.jsonl",),
        steps=(
            "start_chrome_debug.sh puis fetch_auchan_price.py avec QUERY seed.",
            "Accepter cookies via script, rejouer la trace si store perdu.",
            "Extraire prix + prix au litre/kg depuis JSON-LD de la PDP.",
        ),
        outputs=(
            "results/test-<EAN>/latest.json",
            "results/test-<EAN>/summary.json",
        ),
        notes=(
            "Auchan sert de seed prioritaire si Carrefour ne possède pas l'EAN.",
            "Toujours consigner l'URL PDP dans le JSON (champ url).",
        ),
    ),
    "intermarche": MethodSpec(
        key="intermarche",
        enseigne="Intermarché Talence",
        script="fetch_intermarche_price.py",
        summary="Sélectionne l'état sauvegardé du drive Talence puis récupère prix/quantité depuis la PDP.",
        store_hint="Intermarché Talence Drive",
        trace_files=(),
        steps=(
            "Exécuter fetch_intermarche_price.py avec USE_CDP=1 et la QUERY seed.",
            "Attendre le chargement complet de la PDP (refresh auto possible).",
            "Capturer prix TTC + prix au kg + magasin exact.",
        ),
        outputs=(
            "results/test-<EAN>/latest.json",
            "results/test-<EAN>/summary.json",
        ),
        notes=(
            "Toujours renseigner le champ 'note' avec l'horodatage UTC + magasin.",
            "Si le prix au kg n'est pas trouvé, bug à corriger avant de poursuivre.",
        ),
    ),
    "chronodrive": MethodSpec(
        key="chronodrive",
        enseigne="Chronodrive Le Haillan",
        script="fetch_chronodrive_price.py",
        summary="Ferme l'overlay site-search, sélectionne la vignette correspondant au seed puis ouvre la PDP pour extraire prix/unit.",
        store_hint="Chronodrive Le Haillan",
        trace_files=("chronodrive-20250925-5000112611861.jsonl",),
        steps=(
            "start_chrome_debug.sh puis lancer fetch_chronodrive_price.py avec STORE_URL du Haillan.",
            "Fermer l'overlay #site-search après la requête (script géré).",
            "Parcourir la liste et choisir le lien contenant le libellé seed (ou l'EAN).",
            "Ouvrir la PDP, extraire prix TTC, prix/L ou prix/KG, quantité, URL, magasin.",
        ),
        outputs=(
            "results/test-<EAN>/latest.json",
            "results/test-<EAN>/summary.json",
        ),
        notes=(
            "Si le prix diffère du pointage humain (ex: 2,45 €), rejouer la PDP et corriger l'extraction.",
            "Toujours enregistrer une capture lorsque la méthode évolue.",
        ),
    ),
}


def get_method(key: str) -> MethodSpec:
    try:
        return METHODS[key]
    except KeyError as exc:  # pragma: no cover - defensive guard
        raise KeyError(f"Unknown method key: {key}. Known keys: {sorted(METHODS)}") from exc


__all__ = [
    "AUTHORITY_STATEMENT",
    "GLOBAL_IMPERATIVES",
    "MANDATE_VERSION",
    "METHODS",
    "MethodSpec",
    "get_method",
]
