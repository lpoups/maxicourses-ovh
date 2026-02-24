---
name: "chartisme-complet"
description: "Compétence d’analyse chartiste (price action) pour lire la structure de marché, tracer des zones de support/résistance, reconnaître figures et chandeliers, intégrer volume/volatilité et indicateurs (option), puis produire des scénarios conditionnels (A/B/C) avec déclencheur, invalidation, objectifs et gestion du risque."
---

# SKILL: CHARTISME_COMPLET_V1
version: 1.0
last_updated: 2026-02-18
language: fr-FR
domain: trading_technical_analysis
tags: [chartisme, analyse_technique, price_action, support_resistance, figures, chandeliers, indicateurs, ichimoku, wyckoff]
safety: |
  - Fournir un cadre d'analyse probabiliste, pas de certitude.
  - Ne pas promettre de gains. Toujours inclure une gestion du risque.
  - Si l'utilisateur demande un signal "certain" ou des garanties, refuser et proposer une analyse conditionnelle.

## 1) OBJECTIF
Analyser un graphique (ou des données OHLCV) avec une approche chartiste complète, puis produire un plan d'analyse et, si demandé, des scénarios de trading structurés (entrées conditionnelles, invalidation, objectifs, gestion du risque) basés sur:
- Structure de marché (tendance/range/transitions)
- Zones de support/résistance (multi-timeframes)
- Figures chartistes (retournement/continuation)
- Chandeliers japonais (timing)
- Volume/volatilité (effort vs résultat)
- Indicateurs (confirmations)
- Systèmes (Ichimoku, Wyckoff) en option selon le contexte

## 2) QUAND UTILISER
Utiliser ce SKILL quand l'utilisateur fournit au moins un des éléments suivants:
- Un graphique (capture) à analyser
- Des données OHLC / OHLCV
- Un actif + timeframe + contexte de marché (ex: ETH/USD en 4H)

Ne pas utiliser pour:
- Analyse fondamentale, macro, on-chain (sauf demandé explicitement)
- Conseils d'investissement personnalisés (profil, patrimoine, etc.)

## 3) ENTRÉES (INPUT CONTRACT)
### 3.1 Entrées minimales (obligatoires)
- instrument: string (ex: "ETH/USD")
- market_type: enum ["spot","futures","perp","cfd","index","stock","forex","crypto"]
- timeframe: string (ex: "1W","1D","4H","1H","15m","5m")
- data: one of
  - chart_image: image
  - ohlc: array of candles [{{t, o, h, l, c}}] (t = timestamp)
  - ohlcv: array of candles [{{t, o, h, l, c, v}}]

### 3.2 Entrées recommandées (optionnelles mais utiles)
- exchange_or_venue: string (ex: "Binance")
- timezone: string (IANA) (ex: "Europe/Paris")
- price_scale: enum ["linear","log"] (si non fourni: choisir log si longue période/forte amplitude)
- session_context: string (ex: "intraday", "swing", "long terme")
- risk_constraints:
  - max_risk_per_trade_pct: number (ex: 1.0)
  - max_daily_loss_pct: number
  - leverage: number
- user_intent: enum ["analyse_only","trade_setup","education","backtest_rules"]

## 4) SORTIES (OUTPUT CONTRACT)
Toujours produire un résultat en sections standardisées, même si certaines sections sont "N/A".

### 4.1 Format de sortie (strict)
Return a single object-like markdown with these headings in this order:
1. Résumé (1–6 lignes)
2. Contexte multi-timeframes (HTF→LTF)
3. Structure de marché
4. Zones clés (S/R) + justification
5. Figures & patterns (si présents)
6. Chandeliers / signaux de timing (si pertinents)
7. Volume & volatilité (si données volume dispo, sinon N/A)
8. Indicateurs (si demandés ou utiles)
9. Scénarios (A/B/C) avec:
   - Déclencheur (trigger)
   - Invalidation (stop logique)
   - Objectifs (TP1/TP2/TP3)
   - Gestion (trailing, break-even, scaling)
   - Risque (R multiples, position sizing si contraintes fournies)
10. Checklist d’exécution
11. Hypothèses / limites des données

### 4.2 Règles de langage (obligatoires)
- Utiliser un vocabulaire opérationnel: BOS, CHoCH, HL/HH, LH/LL, range, retest, sweep.
- Toujours préciser "zone" plutôt que "niveau" si l'incertitude est élevée.
- Aucune phrase de certitude ("ça va monter"). Utiliser "probable", "scénario", "si/alors".

## 5) PROCÉDURE (ALGORITHM / PLAYBOOK)

### Étape 0 — Validation des entrées
1. Vérifier que instrument + timeframe + data sont présents.
2. Si image: identifier la période visible, l’échelle (log/lin), et les niveaux approximatifs.
3. Si OHLCV: vérifier ordre temporel et absence de valeurs manquantes.
4. Si data insuffisante: analyser ce qui est possible et déclarer les limites.

### Étape 1 — Contexte HTF (Top-Down)
1. Sur HTF (1W/1D si disponibles):
   - déterminer régime: uptrend / downtrend / range.
   - marquer swings clés (HH/HL ou LH/LL) et niveaux majeurs (ATH/ATL, sommets/creux).
2. Définir 2–6 zones HTF maximum (éviter la surcharge).

### Étape 2 — Structure de marché (LTF)
1. Identifier swings récents et structure:
   - BOS (cassure dans le sens du mouvement)
   - CHoCH (cassure opposée)
2. Qualifier le marché:
   - tendance saine (HL/HH) vs tendance affaiblie (perte de momentum)
   - range (bornes claires) vs transition (volatilité/structure instable)
3. Noter la volatilité relative (ATR, amplitude des bougies, squeezes).

### Étape 3 — Supports/Résistances (Zones)
1. Tracer des zones (rectangles) autour:
   - bornes de range
   - creux/hauts significatifs
   - zones de congestion / basing
2. Appliquer la polarité: support cassé → résistance après retest.
3. Classer chaque zone: "majeure" (HTF) / "intermédiaire" / "mineure" (LTF).

### Étape 4 — Figures chartistes
Détecter et qualifier, si visibles:
- Retournement: double top/bottom, ETÊ, arrondis, V-top/V-bottom.
- Continuation: triangles, flags/pennants, rectangles, wedges.
Validation minimale d'une figure:
- contexte compatible + breakout (clôture) + (volume/volatilité ou retest) + invalidation claire.

### Étape 5 — Chandeliers japonais (timing)
1. Rechercher des signaux près des zones:
   - pin bar, engulfing, marteau/pendu, doji (avec confirmation)
2. Interdire l’usage "pattern seul".
3. Fournir toujours:
   - contexte + niveau/zone + invalidation (souvent au-delà de la mèche).

### Étape 6 — Volume & “Effort vs Result” (si volume dispo)
1. Comparer effort (volume) vs résultat (progression du prix).
2. Marquer:
   - absorption (gros volume, faible progrès)
   - climax/capitulation (volume + grande bougie + contexte extrême)
3. Si volume absent: écrire "N/A" et ne pas inférer.

### Étape 7 — Indicateurs (option)
Ne calculer/mentionner que si demandé ou si cela améliore la confluence.
Familles:
- Tendance: EMA/SMA, MACD, ADX
- Momentum: RSI, Stoch, ROC
- Volatilité: ATR, Bollinger/Keltner
- Volume: OBV, VWAP, Volume Profile (si dispo)
Règle: 1–3 indicateurs max. Pas de "indicator soup".

### Étape 8 — Confluence & scoring (recommandé)
Attribuer un score qualitatif (faible/moyen/élevé) basé sur:
- Alignement HTF/LTF
- Qualité zone + réaction
- Validation de figure (breakout/retest)
- Signal chandelier en zone
- Volume/volatilité cohérents

### Étape 9 — Scénarios (A/B/C) + gestion du risque
Produire 1 à 3 scénarios maximum:
- Scénario A: principal (aligné HTF)
- Scénario B: alternative (faux breakout/sweep)
- Scénario C: no-trade (conditions d’annulation)
Chaque scénario doit inclure:
- Trigger (ex: clôture au-dessus de X + retest)
- Invalidation (prix qui rend l’hypothèse fausse)
- Objectifs (TP1/TP2/TP3) via S/R, measured move, extensions
- Gestion (partial, trailing, BE)
- Position sizing (si max_risk_per_trade_pct fourni), sinon indiquer la formule:
  size = (capital * risk%) / (distance_stop)

## 6) CHECKLIST (À RENVOYER À L’UTILISATEUR)
- Régime HTF identifié (trend/range) ?
- Zones HTF marquées (2–6 max) ?
- Trigger défini en une phrase ?
- Invalidation précise (prix) ?
- Stop cohérent avec volatilité (ATR / structure) ?
- Objectifs basés sur niveaux/mesured move ?
- Plan B faux breakout / sweep ?
- R multiples plausibles (>= 1.5R idéalement) ?
- Conditions de non-trade listées ?

## 7) EXEMPLES (TEMPLATES)

### Exemple A — Analyse only
Résumé:
- Marché en range HTF; compression LTF; risque de breakout.

Contexte multi-timeframes:
- 1D: range 2500–3200
- 4H: triangle en formation

Scénarios:
- A: breakout haussier si clôture > 3200 + retest; invalidation sous 3150; TP1 3400, TP2 3600.
- B: faux breakout si wick > 3200 puis réintégration; short sur réintégration; invalidation au-dessus du wick; TP milieu de range.

### Exemple B — Trading plan
- Entrée conditionnelle: stop order au-dessus d’une résistance après squeeze.
- Stop: structure-based au-delà du dernier HL/LH.
- TP: measured move + zones.

## 8) CONTENU DE CONNAISSANCE (REFERENCE NOTES)
Cette section regroupe les notions à connaître et à réutiliser pendant l'analyse, sous forme de rappels.

### 8.1 Cadre mental
- Prix = information agrégée; approche probabiliste; gérer le risque.
- Définir: contexte, déclencheur, invalidation, objectifs, risque.

### 8.2 Structure & zones
- Uptrend: HL→HH; Downtrend: LH→LL; Range: bornes.
- BOS/CHoCH pour détecter continuation vs transition.
- Zones S/R: réactions, tests, polarité, niveaux psychologiques.

### 8.3 Breakouts & faux breakouts
- Breakout validé: clôture + expansion volatilité/volume + retest (option).
- Faux breakout: sweep + réintégration + rejet; cibler milieu/opposé du range.

### 8.4 Figures
- Retournement: double top/bottom, ETÊ, arrondis, V.
- Continuation: triangles, flags, rectangles, wedges.
- Objectifs: hauteur figure / mât / measured move.

### 8.5 Chandeliers
- Marteau/pendu, engulfing, doji, pin bar, étoiles.
- Toujours contextualiser et définir invalidation.

### 8.6 Indicateurs
- Filtrer et confirmer; limiter à 1–3.
- RSI/MACD divergences; ATR pour stops; Bollinger/Keltner pour squeezes.

### 8.7 Ichimoku (option)
- Position prix vs nuage pour biais; signaux Tenkan/Kijun; retest Kijun; rejet Kumo.

### 8.8 Wyckoff (option)
- Accumulation/Distribution; Spring/UTAD; SOS/SOW; LPS/LPSY.
- Trader la réintégration + BOS + invalidation au-delà du sweep.

## 9) JSON SCHEMA (OPTIONNEL POUR OUTILS)
{
  "type": "object",
  "required": [
    "instrument",
    "timeframe",
    "output"
  ],
  "properties": {
    "instrument": {
      "type": "string"
    },
    "timeframe": {
      "type": "string"
    },
    "market_type": {
      "type": "string"
    },
    "output": {
      "type": "object",
      "required": [
        "resume",
        "context_multi_tf",
        "structure",
        "zones",
        "scenarios",
        "checklist",
        "assumptions_limits"
      ],
      "properties": {
        "resume": {
          "type": "string"
        },
        "context_multi_tf": {
          "type": "string"
        },
        "structure": {
          "type": "string"
        },
        "zones": {
          "type": "string"
        },
        "patterns": {
          "type": "string"
        },
        "candles": {
          "type": "string"
        },
        "volume_volatility": {
          "type": "string"
        },
        "indicators": {
          "type": "string"
        },
        "scenarios": {
          "type": "string"
        },
        "checklist": {
          "type": "string"
        },
        "assumptions_limits": {
          "type": "string"
        }
      }
    }
  }
}
