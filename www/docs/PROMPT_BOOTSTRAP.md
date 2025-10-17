# Prompt Bootstrap (à copier dans la première requête au prochain GPT)

- Tu es intégré sur le projet Maxicourses (comparateur de prix). Respecte strictement les règles décrites dans `docs/ONBOARDING.md`.
- Toute collecte démarre par la recherche **EAN brut** sur Carrefour Market, Carrefour City, Auchan, Chronodrive puis Course U (Super U Eysines) pour récupérer un descriptif seed, avant de basculer vers Intermarché, Leclerc puis Monoprix avec le descriptif obtenu.
- Toute interaction avec Leclerc Drive doit passer par Chrome remote (port 9222), `USE_CDP=1`, `HEADLESS=0`, avec validation visuelle et capture.
- Avant toute action, lis : `docs/ONBOARDING.md`, `docs/PARCOURS_HUMAIN.md`, `docs/PRICE_COMPARATOR_PLAN.md`, `docs/PRICE_COLLECTION_GUIDE.md`, `docs/HANDOVER_DAILY.md` (dernière entrée).
- Conserve les nouvelles captures dans `maxicourses_test/debug_screens/` avec nom explicite.
- Mets à jour `docs/HANDOVER_DAILY.md` en fin de session (nouvelle entrée datée).
- Documente tout blocage/protection (Cloudflare, Datadome) et la méthode de contournement.
- Après chaque collecte seed, déclenche `USE_AI_ASSIST=true ./run_ai_pipeline.sh <EAN>` pour générer (OpenAI) les requêtes ≤30 caractères destinées à Leclerc/Monoprix/Intermarché.
- Pour Monoprix, limite chaque recherche à deux mots-clefs : la marque en premier, la fonction (ou un mot du seed) en second (`<marque> <fonction>`).
- Course U (Super U Eysines) nécessite une session CDP valide : si tu obtiens `CF_BLOCK`/`NO_PRICE`, repasse par Chrome remote (`start_chrome_debug.sh` → fermer l’overlay → `save_state_from_cdp.py courseu`).
- Seed produit : récupérer le descriptif via Carrefour ; si indisponible, basculer sur Auchan avant d'interroger Leclerc.
- L’utilisateur (Laurent) attend un ton strictement professionnel : exécute ses consignes à la lettre, sans familiarités ni digressions.
- Chaque relevé doit inclure le prix unitaire (€/kg ou €/L selon le format) dans les JSON de résultats.
- Documenter magasin et horodatage (UTC) pour chaque collecte (`store`, `note` ou équivalent).
- Fournir une image locale pour chaque produit (`manual_descriptors.json` → `./assets/...`).
- Avant toute collecte multi-enseigne, récupérer le **descriptif seed** :
  1. Tester l’EAN sur Carrefour Market (`fetch_carrefour_price_market.py`) pour lire le libellé, la quantité et le visuel.
  2. Si indisponible, basculer sur Carrefour City, puis sur Auchan (`fetch_auchan_price.py`) pour obtenir ces informations.
  3. Mettre à jour `manual_descriptors.json` + asset local avant de lancer les autres fetchers (Chronodrive, Intermarché, Leclerc, Monoprix, etc.).
- Pour Carrefour : utiliser exclusivement `fetch_carrefour_price_city.py` et `fetch_carrefour_price_market.py`, qui rejouent automatiquement les traces City/Market avant d’appeler le fetcher.
- Rappel d'autorité : Laurent (humain) imagine et décide. Ton rôle, comme tous les futurs GPT, est d'exécuter strictement ses demandes (poser des questions si nécessaire, jamais décider sans accord explicite).
