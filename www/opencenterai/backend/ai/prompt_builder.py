"""
OpenCenterAI Trading - AI Prompt Builder
=========================================
Extracted from refonte_v2.py (2026-02-21).
Builds system prompts, user prompts, and tool_use schema for Claude API.

Responsibilities:
- build_claude_system_prompt() - Stable system prompt (cached via cache_control)
- build_ai_prompt_v2() - Variable market data prompt per cycle
- get_trading_decision_tool() - tool_use schema (structured output)
- format_candle_data() / format_indicator_snapshot() - Data formatting helpers

IMPORTANT: The tool_use schema defines the contract between Claude and the engine.
Any change here must be mirrored in ai.decision sanitizer.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict


# ===================================================================
# SKILL.md + chartisme-complet.md -- Loaded ONCE at startup
# ===================================================================
_SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")

_SKILL_CONTENT = ""
_SKILL_PATH = os.path.join(_SKILLS_DIR, "SKILL.md")
try:
    with open(_SKILL_PATH, "r", encoding="utf-8") as _f:
        _SKILL_CONTENT = _f.read().strip()
except Exception:
    pass  # SKILL.md absent -- not blocking

_CHARTISME_CONTENT = ""
_CHARTISME_PATH = os.path.join(_SKILLS_DIR, "chartisme-complet.md")
try:
    with open(_CHARTISME_PATH, "r", encoding="utf-8") as _f:
        _CHARTISME_CONTENT = _f.read().strip()
except Exception:
    pass  # chartisme-complet.md absent -- not blocking


# ===================================================================
# TOOL_USE SCHEMA -- Structured Outputs (no fragile JSON parsing)
# ===================================================================

def get_trading_decision_tool() -> Dict[str, Any]:
    """
    Tool definition for Claude tool_use -- guaranteed structured output.
    No JSON parsing, no ```json, no truncation.
    The Claude API returns a valid Python dict directly.
    """
    return {
        "name": "trading_decision",
        "description": "Enregistre ta decision de trading apres analyse chartiste complete. Utilise TOUJOURS cet outil pour repondre.",
        "input_schema": {
            "type": "object",
            "properties": {
                "regime": {
                    "type": "string",
                    "enum": ["TREND_UP", "TREND_DOWN", "RANGE", "TRANSITION"],
                    "description": "Regime de marche identifie"
                },
                "direction": {
                    "type": "string",
                    "enum": ["BULLISH", "BEARISH", "NEUTRAL"],
                    "description": "Direction generale du marche"
                },
                "action": {
                    "type": "string",
                    "enum": [
                        "LONG", "SHORT", "WAIT", "KEEP",
                        "EXIT_LONG", "EXIT_SHORT",
                        "PARTIAL_EXIT_LONG", "PARTIAL_EXIT_SHORT",
                        "HEDGE_LONG", "HEDGE_SHORT",
                    ],
                    "description": "PARTIAL_EXIT=securise 50%. HEDGE=ouvrir position opposee SANS fermer l'existante (couverture)"
                },
                "trend_strength": {
                    "type": "integer",
                    "description": "Force de la tendance (0-100)"
                },
                "confidence": {
                    "type": "integer",
                    "description": "Niveau de confiance dans la decision (0-100)"
                },
                "entry_mode": {
                    "type": "string",
                    "enum": ["BREAKOUT", "PULLBACK", "RANGE_BOUNCE", "MEAN_REVERSION", "NONE"],
                    "description": "Mode d'entree si LONG/SHORT"
                },
                "position_advice": {
                    "type": "string",
                    "enum": ["KEEP", "QUITTER", "SECURISER", "HEDGE"],
                    "description": "KEEP=garder, QUITTER=tout fermer, SECURISER=50%, HEDGE=ouvrir position opposee en couverture"
                },
                "score_long": {
                    "type": "integer",
                    "description": "Score haussier (0-100)"
                },
                "score_short": {
                    "type": "integer",
                    "description": "Score baissier (0-100)"
                },
                "wait_reason_code": {
                    "type": "string",
                    "enum": [
                        "NONE", "LOW_EDGE", "MTF_CONFLICT", "LOW_VOLUME",
                        "NO_SETUP", "COUNTER_TREND", "RANGE_BOUND", "OTHER",
                    ],
                    "description": "Raison du WAIT si applicable"
                },
                "horizon_forecast": {
                    "type": "object",
                    "properties": {
                        "15m": {"type": "string", "enum": ["BULL", "BEAR", "NEUTRAL"]},
                        "30m": {"type": "string", "enum": ["BULL", "BEAR", "NEUTRAL"]},
                        "1h": {"type": "string", "enum": ["BULL", "BEAR", "NEUTRAL"]},
                        "4h": {"type": "string", "enum": ["BULL", "BEAR", "NEUTRAL"]},
                    },
                    "required": ["15m", "30m", "1h", "4h"],
                    "description": "Prevision par horizon temporel"
                },
                "trigger_snapshot": {
                    "type": "string",
                    "description": "Resume compact: struct=X zone=Y pat=Z vol=W conf=N"
                },
                "thinking": {
                    "type": "string",
                    "description": "Raisonnement chartiste condense (max 150 chars)"
                },
                "reason": {
                    "type": "string",
                    "description": "Justification technique (max 25 mots)"
                },
                "size": {
                    "type": "number",
                    "description": "Taille de position recommandee"
                },
                "target": {
                    "type": "number",
                    "description": "Niveau de take-profit (0 si WAIT)"
                },
                "stop": {
                    "type": "number",
                    "description": "Niveau de stop-loss (0 si WAIT)"
                },
                "invalidation_level": {
                    "type": "number",
                    "description": "Niveau d'invalidation du setup"
                },
            },
            "required": [
                "regime", "direction", "action", "trend_strength", "confidence",
                "entry_mode", "position_advice", "score_long", "score_short",
                "wait_reason_code", "horizon_forecast", "trigger_snapshot",
                "thinking", "reason", "size", "target", "stop", "invalidation_level",
            ],
        },
    }


# ===================================================================
# SYSTEM PROMPTS
# ===================================================================

def build_claude_system_prompt(
    has_position: bool = False,
    position_direction: str = "",
    market_risk_score: int = 50,
    risk_label: str = "MODERE",
    partial_profit_eur: float = 8.0,
    full_profit_eur: float = 15.0,
) -> str:
    """
    Stable system prompt for Claude -- cached via cache_control (ephemeral).
    Switches between surveillance mode and position management mode.
    """
    base = (
        "Tu es un CHARTISTE ETH/USD expert en Price Action et structure de marche.\n"
        "APPROCHE: Probabiliste, conditionnelle (si/alors). ZERO certitude, ZERO psychologie.\n"
        "Le PRIX est l'information. Tu lis les bougies, la structure, les zones, le volume.\n"
        "VOCABULAIRE: BOS (Break of Structure), CHoCH (Change of Character), HH/HL (Higher High/Low),\n"
        "LH/LL (Lower High/Low), sweep, retest, polarite, Order Block, absorption, climax.\n"
    )

    if has_position:
        return _build_position_management_prompt(
            base,
            position_direction,
            market_risk_score=market_risk_score,
            risk_label=risk_label,
            partial_profit_eur=partial_profit_eur,
            full_profit_eur=full_profit_eur,
        )

    return _build_surveillance_prompt(base)


def _build_position_management_prompt(
    base: str,
    position_direction: str,
    market_risk_score: int = 50,
    risk_label: str = "MODERE",
    partial_profit_eur: float = 8.0,
    full_profit_eur: float = 15.0,
) -> str:
    """Position management prompt -- manages an already open position."""
    pos_dir_label = "BUY (LONG)" if str(position_direction).upper() in ("BUY", "LONG") else "SELL (SHORT)"
    exit_action = "EXIT_LONG" if str(position_direction).upper() in ("BUY", "LONG") else "EXIT_SHORT"
    is_long = str(position_direction).upper() in ("BUY", "LONG")

    return (
        base
        + f"\n=== MODE: GESTION DE POSITION {pos_dir_label} ===\n"
        f"Position DEJA ouverte en {pos_dir_label}. Tu ne cherches PAS de nouvelle entree.\n\n"

        "PHILOSOPHIE: GAINS REGULIERS > COUPS DE POKER\n"
        "- On NE JOUE PAS au loto. On securise des gains raisonnables.\n"
        "- Un gain PRIS (+10-20EUR) vaut mieux qu'un gain ESPERE (+40EUR) qui revient a 0.\n"
        "- PROFIT > 10EUR -> penser SECURISATION, pas continuation a tout prix.\n"
        "- EXIT = decision PRAGMATIQUE, pas signe de faiblesse.\n\n"

        f"TES SEULES OPTIONS: KEEP ou {exit_action}\n"
        "INTERDIT de repondre action='LONG' ou action='SHORT'.\n\n"

        "=== PROCEDURE D'ANALYSE EN 6 ETAPES ===\n\n"

        "ETAPE 1 -- LE SETUP EST-IL ENCORE VALIDE?\n"
        "  - PnL positif + structure intacte -> KEEP (haute confiance)\n"
        "  - PnL negatif mais setup intact (S/R protegent, pas de CHoCH) -> KEEP (patience)\n"
        "  - CHoCH CONFIRME en cloture 15m+ CONTRE la position -> EXIT possible\n"
        "  - Simple pullback, meche, bougie contraire 1m/5m = BRUIT -> KEEP\n\n"

        "ETAPE 2 -- ZONES S/R PROTECTRICES\n"
        f"  Pour un {'LONG' if is_long else 'SHORT'}:\n"
        f"  - {'Support intact sous le prix -> KEEP' if is_long else 'Resistance intacte au-dessus du prix -> KEEP'}\n"
        f"  - Polarite: {'support casse en CLOTURE 15m -> alerte EXIT' if is_long else 'resistance cassee en CLOTURE 15m -> alerte EXIT'}\n"
        "  - MECHE qui traverse sans cloture = sweep/faux breakout -> KEEP\n\n"

        "ETAPE 3 -- PATTERNS & CHANDELIERS\n"
        "  KEEP: flags, pennants, triangles de continuation, pin bar/marteau pro-position\n"
        "  EXIT: double top/bottom, ETE, V-reversal CONFIRME sur 15m+ avec volume\n\n"

        "ETAPE 4 -- VOLUME & EFFORT vs RESULTAT (Wyckoff)\n"
        "  - Volume croissant dans le sens de la position = mouvement sain -> KEEP\n"
        "  - Volume faible en correction = pullback normal -> KEEP\n"
        "  - Absorption (gros volume, prix stagne) = epuisement -> vigilance\n"
        "  - Climax (volume extreme + grande bougie contre) = retournement possible -> EXIT si confirme\n\n"

        "ETAPE 5 -- INDICATEURS (1-3 max, confirmation)\n"
        "  - RSI divergence confirmee 15m+ CONTRE la position -> alerte EXIT\n"
        "  - MACD croisement contre la position sur 15m/1h -> alerte\n"
        "  - ATR eleve = volatilite normale crypto -> elargir la tolerance, PAS sortir\n\n"

        f"ETAPE 6 -- DECISION BASEE SUR LE RISQUE MARCHE\n"
        f"  RISQUE MARCHE ACTUEL: {market_risk_score}/100 ({risk_label})\n"
        f"  Seuils dynamiques: PARTIAL >= {partial_profit_eur}EUR | EXIT TOTAL >= {full_profit_eur}EUR\n"
        "  PARTIAL_EXIT = fermer la MOITIE, garder le RESTE.\n\n"

        "  PnL TRES NEGATIF (perte > -10EUR): Setup casse -> EXIT total\n"
        "  PnL NEGATIF MODERE (-1 a -10EUR): Setup intact -> KEEP. Signaux mixtes -> PARTIAL_EXIT\n"
        f"  PnL SOUS SEUIL PARTIAL (< +{partial_profit_eur}EUR): Trend fort -> KEEP. Mixte -> PARTIAL_EXIT\n"
        f"  PnL ENTRE SEUILS (+{partial_profit_eur}EUR a +{full_profit_eur}EUR): Trend intact -> PARTIAL_EXIT\n"
        f"  PnL AU-DESSUS DU SEUIL FULL (>= +{full_profit_eur}EUR): Acceleration -> PARTIAL_EXIT. Sinon -> EXIT total.\n\n"

        "=== REGLES BON PERE DE FAMILLE ===\n"
        "1. PARTIAL_EXIT = reduire le risque de moitie. Valable EN GAIN et EN PERTE.\n"
        "2. En perte + doute -> PARTIAL_EXIT (pas EXIT total, ni KEEP total).\n"
        "3. En gain + trend intact -> PARTIAL_EXIT (pas EXIT total).\n"
        "4. EXIT total = seulement quand le setup est CLAIREMENT invalide ou gain enorme.\n"
        "5. KEEP total = seulement quand le setup est INTACT et le PnL est faible.\n"
        "6. Si tu hesites -> PARTIAL_EXIT. C'est toujours le choix raisonnable.\n\n"

        "=== HEDGE (COUVERTURE) ===\n"
        "  HEDGE = ouvrir une position OPPOSEE SANS fermer l'existante.\n"
        "  Reserve aux situations EXCEPTIONNELLES (V-reversal, flash crash, news choc).\n"
        "  En situation normale -> utilise KEEP, PARTIAL_EXIT ou EXIT, pas HEDGE.\n\n"

        "=== CONFIDENCE ===\n"
        "  KEEP haute confiance (75-100%): Setup solide + momentum + PnL faible\n"
        "  PARTIAL_EXIT defensif (60-75%): Incertitude ou PnL negatif, reduire risque\n"
        "  PARTIAL_EXIT securisation (65-80%): PnL bon/excellent + trend intact\n"
        f"  {exit_action} prise de gain totale (65-80%): PnL bon + momentum casse\n"
        f"  {exit_action} stop loss (55-65%): Setup invalide, couper la perte\n\n"

        "=== REPONSE ===\n"
        "Utilise l'outil trading_decision pour enregistrer ta decision.\n"
        "Sois CONCIS: thinking max 150 chars, reason max 25 mots.\n"
        f"Actions possibles: KEEP, PARTIAL_EXIT_LONG/SHORT, {exit_action}, HEDGE_LONG/SHORT.\n"
    ) + (
        f"\n\n=== SKILLS REFERENCE (Trading Knowledge Base) ===\n{_SKILL_CONTENT}\n"
        + (f"\n=== CHARTISME COMPLET ===\n{_CHARTISME_CONTENT}\n" if _CHARTISME_CONTENT else "")
        if _SKILL_CONTENT else ""
    )


def _build_surveillance_prompt(base: str) -> str:
    """Surveillance prompt (no open position) -- searches for high-quality entries."""
    return (
        base
        + "\n=== MODE: SURVEILLANCE -- RECHERCHE D'ENTREE ===\n"
        "Pas de position ouverte. Tu cherches des entrees de HAUTE QUALITE.\n\n"

        "REGLE N1: LE PRIX EST ROI -- LE 4H EST CONTEXTE\n"
        "Le trend_4h_bias est un CONTEXTE important, PAS un veto absolu.\n"
        "Le 4H utilise des EMA lentes (20/50) qui RETARDENT sur les mouvements forts.\n"
        "  -> trend_4h_bias = BULL -> PREFERER LONG. SHORT accepte si CHoCH 1H confirme.\n"
        "  -> trend_4h_bias = BEAR -> PREFERER SHORT. LONG accepte si BOS haussier 1H.\n"
        "  -> trend_4h_bias = NEUTRAL -> les deux directions sont autorisees.\n\n"

        "=== PROCEDURE CHARTISTE EN 7 ETAPES ===\n\n"

        "ETAPE 1 -- REGIME DE MARCHE (Multi-TF: 5m -> 15m -> 1h -> 4h)\n"
        "  Qualifier: TREND_UP / TREND_DOWN / RANGE / TRANSITION\n\n"

        "ETAPE 2 -- STRUCTURE DE MARCHE (Price Action)\n"
        "  BOS = continuation. CHoCH = possible retournement.\n"
        "  CHoCH sur 5m = faible. CHoCH sur 15m = preparer. CHoCH sur 1h = TRADER.\n\n"

        "ETAPE 3 -- ZONES CLES (Support / Resistance)\n"
        "  2-6 zones max. Polarite: support casse -> resistance (et vice versa).\n\n"

        "ETAPE 4 -- PATTERNS & CHANDELIERS (Triggers d'entree)\n"
        "  EN TREND: pullback vers EMA21/50, chandeliers de rejet, BOS continuation\n"
        "  EN RANGE: prix aux bornes + rejet. Sweep de liquidite = excellent signal.\n\n"

        "ETAPE 5 -- VOLUME & EFFORT vs RESULTAT (Wyckoff)\n"
        "  Breakout + volume croissant = VALIDE. Breakout + volume faible = FAUX.\n\n"

        "ETAPE 6 -- INDICATEURS (confirmation, 1-3 max)\n"
        "  RSI, MACD, Stochastique, ATR, Bollinger -- CONFIRMATION, pas signal principal.\n\n"

        "ETAPE 7 -- DECISION PAR CONFLUENCE (Score)\n"
        "  4+ points = HAUTE confluence -> TRADE 75-95%\n"
        "  3 points = bonne confluence -> TRADE 65-74%\n"
        "  2 points = faible -> TRADE prudent ou WAIT\n"
        "  1 point = WAIT sauf setup parfait sur zone S/R extreme\n\n"

        "=== REGLES IMPERATIVES ===\n"
        "1. MOMENTUM DOMINE: trade avec la direction dominante actuelle (5m+15m+1H).\n"
        "2. CONFLUENCE MINIMUM: zone S/R + pattern/structure + 1 indicateur = 3 elements.\n"
        "3. RANGE TRADING: LONG au support, SHORT a la resistance.\n"
        "4. FAUX BREAKOUT = TRADE: sweep de liquidite + reintegration = excellent signal.\n"
        "5. SL = sous/au-dessus de la zone S/R. MINIMUM 25 points.\n"
        "6. R:R MINIMUM = 1.5:1.\n\n"

        "=== CONFIDENCE ===\n"
        "  85-95%: Tous TFs alignes + zone S/R + pattern + volume + indicateur\n"
        "  75-84%: 1H aligne + zone S/R + pattern\n"
        "  65-74%: 15m+1H alignes mais 4H oppose -> TRADE de reversal\n"
        "  60-64%: zone S/R + indicateur extreme -> TRADE prudent\n"
        "  < 60%: WAIT\n\n"

        "=== REPONSE ===\n"
        "Utilise l'outil trading_decision pour enregistrer ta decision.\n"
        "Sois CONCIS: thinking max 150 chars, reason max 25 mots.\n"
        "action = LONG, SHORT ou WAIT.\n"
    ) + (
        f"\n\n=== SKILLS REFERENCE (Trading Knowledge Base) ===\n{_SKILL_CONTENT}\n"
        + (f"\n=== CHARTISME COMPLET ===\n{_CHARTISME_CONTENT}\n" if _CHARTISME_CONTENT else "")
        if _SKILL_CONTENT else ""
    )


# ===================================================================
# USER PROMPT (variable data per cycle)
# ===================================================================

def build_ai_prompt_v2(snapshot: Dict[str, Any]) -> str:
    """
    User prompt with variable cycle data.
    Sent as a user message (not cached).
    """
    payload = json.dumps(snapshot, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return (
        "DONNEES DU CYCLE ACTUEL:\n"
        f"{payload}\n\n"
        "ANALYSE CHARTISTE COMPLETE -- Suis les 7 etapes:\n"
        "1) Regime: lis trend_4h_bias (DIRECTION) + trend_1h_bias (confirmation)\n"
        "2) Structure: BOS/CHoCH, HH/HL ou LH/LL, swing points\n"
        "3) Zones S/R: zones majeures (HTF), Order Blocks, polarite\n"
        "4) Patterns: chandeliers de rejet, figures (flag/triangle/ETE), breakouts\n"
        "5) Volume: effort vs resultat, absorption, climax, spring/UTAD\n"
        "6) Indicateurs: RSI/Stoch/MACD (confirmation, pas signal principal)\n"
        "7) Confluence: score 0-5 -> decision\n\n"
        "Si une image chart est jointe, lis les bougies et la structure en priorite.\n"
        "RAPPEL: trend_4h_bias = CONTEXTE. Si 1H+15m sont alignes dans la direction opposee au 4H -> c'est une REVERSAL, trade-la.\n"
        "Crypto = volatile. Les corrections sont normales. Aie CONFIANCE dans ton analyse.\n"
        "Utilise l'outil trading_decision pour enregistrer ta decision."
    )


# ===================================================================
# DATA FORMATTING HELPERS
# ===================================================================

def format_candle_data(candles: list, max_candles: int = 20) -> str:
    """Format OHLCV candle data for prompt insertion."""
    if not candles:
        return "No candle data available."
    lines = []
    for c in candles[-max_candles:]:
        if not isinstance(c, dict):
            continue
        o = round(float(c.get("open", 0)), 2)
        h = round(float(c.get("high", 0)), 2)
        lo = round(float(c.get("low", 0)), 2)
        cl = round(float(c.get("close", 0)), 2)
        v = int(float(c.get("volume", 0)))
        d = "+" if cl >= o else "-"
        lines.append(f"  O={o} H={h} L={lo} C={cl} V={v} {d}")
    return "\n".join(lines) if lines else "No valid candle data."


def format_indicator_snapshot(indicators: Dict[str, Any]) -> str:
    """Format a dict of indicator values for prompt insertion."""
    if not indicators:
        return "No indicator data available."
    lines = []
    for key, val in sorted(indicators.items()):
        if isinstance(val, float):
            lines.append(f"  {key}: {val:.4f}")
        else:
            lines.append(f"  {key}: {val}")
    return "\n".join(lines)
