# OpenCenterAI Trading Skills

## Format: YAML skill definitions pour Claude API tool_use

```yaml
# ═══════════════════════════════════════════════════════════════
# SKILL 1: ANALYSE CHARTISTE (Price Action & Structure)
# ═══════════════════════════════════════════════════════════════
chartist_analysis:
  name: "Analyse Chartiste Complète"
  description: "Analyse price action, structure de marché et patterns"
  priority: HIGHEST

  structure_analysis:
    bos:
      name: "Break of Structure (BOS)"
      description: "Cassure d'un swing high/low précédent"
      bullish: "Prix casse au-dessus du dernier swing high → continuation haussière"
      bearish: "Prix casse en dessous du dernier swing low → continuation baissière"
      weight: 30

    choch:
      name: "Change of Character (CHoCH)"
      description: "Premier signe de retournement de tendance"
      bullish: "Higher Low dans un downtrend → début de reversal haussière"
      bearish: "Lower High dans un uptrend → début de reversal baissière"
      timeframe_importance:
        5m: "Signal précoce — attendre confirmation 15m"
        15m: "Signal modéré — préparer entrée"
        1h: "Signal FORT — trader la reversal"
        4h: "Signal confirmé — nouvelle direction"
      weight: 25

    swing_structure:
      uptrend: "HH (Higher Highs) + HL (Higher Lows)"
      downtrend: "LH (Lower Highs) + LL (Lower Lows)"
      range: "Equal highs + Equal lows"

  order_blocks:
    name: "Order Blocks (OB)"
    description: "Zones d'ordres institutionnels"
    identification: "Dernière bougie opposée avant un mouvement impulsif fort"
    bullish_ob: "Dernière bougie baissière avant forte impulsion haussière"
    bearish_ob: "Dernière bougie haussière avant forte impulsion baissière"
    trading_rule: "Attendre le retour du prix dans l'OB pour entrer"
    weight: 20

  fair_value_gaps:
    name: "Fair Value Gaps (FVG / Imbalance)"
    description: "Zones de déséquilibre de prix"
    identification: "Gap entre la mèche haute de bougie 1 et mèche basse de bougie 3"
    trading_rule: "Le prix tend à revenir combler le FVG"
    weight: 15

  support_resistance:
    name: "Support & Résistance"
    rules:
      - "Utiliser les swing highs/lows RÉCENTS (pas les vieux niveaux)"
      - "Zone = rectangle, pas une ligne. Tolérance de quelques points"
      - "Support cassé en clôture → devient résistance (polarité)"
      - "Résistance cassée en clôture → devient support (polarité)"
      - "Niveaux psychologiques: 1800, 1850, 1900, 1950, 2000..."
    hierarchy:
      majeure: "Visible sur 4h/1h — poids fort"
      intermediaire: "Visible sur 15m — poids moyen"
      mineure: "Visible sur 5m — poids faible"
    weight: 20

# ═══════════════════════════════════════════════════════════════
# SKILL 2: PATTERNS CHARTISTES
# ═══════════════════════════════════════════════════════════════
chart_patterns:
  name: "Reconnaissance de Patterns"
  description: "Identification et trading des figures chartistes"

  reversal_patterns:
    head_and_shoulders:
      type: "bearish_reversal"
      trigger: "Cassure de la neckline en clôture"
      target: "Hauteur de la tête projetée depuis la neckline"
      invalidation: "Prix repasse au-dessus de l'épaule droite"
      rule: "INVALIDE tant que la neckline n'est pas cassée"

    inverse_head_and_shoulders:
      type: "bullish_reversal"
      trigger: "Cassure de la neckline en clôture"
      target: "Hauteur de la tête projetée depuis la neckline"
      invalidation: "Prix repasse en dessous de l'épaule droite"

    double_top:
      type: "bearish_reversal"
      trigger: "Cassure du creux intermédiaire (neckline)"
      target: "Hauteur du pattern projetée vers le bas"
      rule: "INVALIDE tant que la neckline n'est pas cassée — 2 tests de résistance ne suffisent PAS"

    double_bottom:
      type: "bullish_reversal"
      trigger: "Cassure du sommet intermédiaire (neckline)"
      target: "Hauteur du pattern projetée vers le haut"
      rule: "INVALIDE tant que la neckline n'est pas cassée"

  continuation_patterns:
    bull_flag:
      type: "bullish_continuation"
      description: "Consolidation baissière dans un uptrend"
      trigger: "Cassure du haut du flag avec volume"
      target: "Hauteur du mât projetée"

    bear_flag:
      type: "bearish_continuation"
      description: "Consolidation haussière dans un downtrend"
      trigger: "Cassure du bas du flag avec volume"
      target: "Hauteur du mât projetée"

    ascending_triangle:
      type: "bullish"
      description: "Résistance horizontale + supports montants"
      trigger: "Cassure de la résistance horizontale"

    descending_triangle:
      type: "bearish"
      description: "Support horizontal + résistances descendantes"
      trigger: "Cassure du support horizontal"

    symmetric_triangle:
      type: "neutre — direction de la cassure"
      description: "Supports montants + résistances descendantes"
      trigger: "Cassure dans une direction avec volume"

  warning_patterns:
    rising_wedge:
      type: "bearish"
      description: "Supports et résistances convergents montants"
      rule: "Bearish UNIQUEMENT après cassure du support du wedge"
      warning: "Tant que le prix est DANS le wedge, il peut encore monter!"

    falling_wedge:
      type: "bullish"
      description: "Supports et résistances convergents descendants"
      rule: "Bullish UNIQUEMENT après cassure de la résistance du wedge"

  confirmation_rule: |
    AUCUN pattern n'est valide avant la cassure de son trigger.
    Ne JAMAIS pré-trader un pattern non confirmé.
    La cassure doit être accompagnée de volume pour être valide.

# ═══════════════════════════════════════════════════════════════
# SKILL 3: MULTI-TIMEFRAME ANALYSIS
# ═══════════════════════════════════════════════════════════════
multi_timeframe:
  name: "Analyse Multi-Timeframe"
  description: "Coordination entre timeframes — LE PRIX MÈNE, le 4H SUIT"

  hierarchy:
    - timeframe: "4H"
      role: "CONTEXTE de fond (EMA 20/50 — LENT, retarde sur les reversals)"
      usage: "Identifier la tendance de fond. ATTENTION: pendant les reversals rapides, le 4H montre ENCORE l'ancienne direction"

    - timeframe: "1H"
      role: "Direction DOMINANTE actuelle"
      usage: "C'est le timeframe le plus fiable pour la direction RÉELLE du marché"

    - timeframe: "15m"
      role: "Timing d'entrée et signaux précoces"
      usage: "CHoCH sur 15m = signal précoce de reversal"

    - timeframe: "5m"
      role: "Exécution et micro-structure"
      usage: "Timing précis d'entrée, confirmation de momentum"

  reversal_detection:
    rule: |
      Les REVERSALS commencent TOUJOURS sur les timeframes inférieurs.
      Un BOS haussier sur 1H avec volume est VALIDE même si 4H est BEAR.
      Le 4H confirmera le mouvement APRÈS — quand les EMA se retourneront.
      Si tu attends la confirmation 4H, tu rates 80% du mouvement.

    signals:
      strong_reversal:
        description: "5m + 15m + 1H tous alignés dans la direction opposée au 4H"
        action: "TRADER avec confiance 65-78%"

      moderate_reversal:
        description: "15m + 1H alignés dans la direction opposée au 4H"
        action: "TRADER avec confiance 65-74%"

      early_reversal:
        description: "Seulement 15m montre CHoCH"
        action: "SURVEILLER — attendre confirmation 1H"

      no_reversal:
        description: "Seulement 5m montre un signal opposé au 4H"
        action: "IGNORER — probablement du bruit"

  alignment_scoring:
    all_aligned: "80-95% confiance"
    3_of_4: "70-84% confiance"
    2_of_4: "60-74% confiance"
    1_of_4: "< 60% — WAIT recommandé"

# ═══════════════════════════════════════════════════════════════
# SKILL 4: INDICATEURS TECHNIQUES (CONFIRMATION, PAS SIGNAL)
# ═══════════════════════════════════════════════════════════════
technical_indicators:
  name: "Indicateurs Techniques"
  role: "CONFIRMATION du price action — jamais signal principal"

  rsi:
    oversold: "< 30 → zone de rebond potentiel"
    overbought: "> 70 → zone de correction potentielle"
    rule: "RSI overbought dans un UPTREND = NORMAL (pas un signal de vente)"
    divergence: "RSI divergence + cassure de structure = signal fort"

  stochastic:
    oversold: "< 20 → zone de rebond"
    overbought: "> 80 → zone de correction"
    rule: "Stoch peut rester en zone extrême longtemps dans un trend fort"
    best_use: "Croisement K/D en zone extrême + zone S/R = bon signal"

  macd:
    signal: "Croisement MACD/signal"
    histogram: "Changement de momentum"
    divergence: "MACD divergence = signal fort de reversal"

  volume:
    breakout: "Cassure avec volume élevé (> 1.5x moyenne) = VALIDE"
    no_volume: "Cassure sans volume = FAUX BREAKOUT probable"
    climax: "Volume extrême + bougie d'épuisement = reversal possible"

  atr:
    usage: "Mesure la volatilité pour SL/TP"
    sl_rule: "SL = 1.0-1.5 ATR(15m). MINIMUM ABSOLU = 25 points (1.3% du prix). IG rejette les stops < 20pts. Utiliser ATR du 15m, pas du 5m."
    tp_rule: "TP = 1.5-2.5 ATR pour R:R minimum 1.5:1"
    warning: "ATR du 5m est TROP PETIT pour le SL. Toujours utiliser ATR(15m) ou ATR(1H) pour le calcul du SL."

# ═══════════════════════════════════════════════════════════════
# SKILL 5: GESTION DU RISQUE
# ═══════════════════════════════════════════════════════════════
risk_management:
  name: "Gestion du Risque"
  description: "Taille fixe, SL/TP basés sur structure et ATR"

  position_size: 2.0  # ETH fixe

  stop_loss:
    placement: "Toujours derrière un niveau de structure (swing, S/R, OB)"
    minimum: "25 points minimum (1.3% du prix). IG rejette les stops < 20pts. JAMAIS en dessous de 25pts."
    ideal: "25-40 points (1.3%-2.0% du prix) selon volatilité"
    maximum: "50 points maximum pour ETH"
    atr_rule: "SL = 1.0-1.5 × ATR(15m). Si ATR(15m) < 25pts, utiliser 25pts minimum."
    rule: "SL trop serré = stop fréquents sur le bruit. SL trop large = pertes lourdes."

  take_profit:
    placement: "Prochaine zone S/R significative"
    minimum_rr: 1.3
    ideal_rr: "1.5 à 2.5"
    rule: "Toujours définir TP AVANT l'entrée"

  daily_limits:
    max_loss: 50  # EUR
    hard_cap: 80  # EUR
    max_positions: 2
    max_exposure: 4.0  # ETH

  trailing_stop:
    enabled: true
    rule: "Le trailing protège les gains — laisser courir les gagnants"

# ═══════════════════════════════════════════════════════════════
# SKILL 6: SMART MONEY CONCEPTS (SMC)
# ═══════════════════════════════════════════════════════════════
smart_money:
  name: "Smart Money Concepts"
  description: "Trading institutionnel — liquidity sweeps, order flow"

  liquidity:
    buy_side: "Pool de stop-loss au-dessus des swing highs"
    sell_side: "Pool de stop-loss en dessous des swing lows"
    sweep: "Prix prend la liquidité puis reverse → excellent signal d'entrée"
    rule: "Un sweep de liquidité + réintégration = faux breakout = signal de trade"

  order_flow:
    exhaustion: "Beaucoup d'ordres dans une direction + prix qui stagne = fin de mouvement"
    absorption: "Gros volume sans mouvement de prix = ordres absorbés par les institutionnels"
    impulse: "Mouvement fort avec volume = direction vraie"

  market_phases:
    accumulation: "Range après un downtrend → smart money achète"
    markup: "Mouvement haussier après accumulation"
    distribution: "Range après un uptrend → smart money vend"
    markdown: "Mouvement baissier après distribution"
```

## Utilisation

Ce fichier SKILL.md est la référence des compétences de trading pour l'IA ProphetV3.
Les skills sont intégrés dans le system prompt de Claude Haiku via `refonte_v2.py` et `prophet_engine.py`.

### Philosophie: "Trust Claude, Execute Fast, Log Everything"
- L'IA (Claude) est le cerveau — elle analyse et décide
- Le moteur (trading_engine.py) exécute sans bloquer
- MongoDB enregistre chaque décision

### Règle d'or
**Le PRIX est roi. Le 4H est contexte, pas veto.**
Les reversals commencent sur les timeframes inférieurs.
Ne jamais bloquer un signal LONG/SHORT uniquement parce que le 4H est opposé.
