# Prompt Bootstrap (à copier dans la première requête au prochain GPT)

- Tu es intégré sur le projet Maxicourses (comparateur de prix). Respecte strictement les règles décrites dans `docs/ONBOARDING.md`.
- Toute interaction avec Leclerc Drive doit passer par Chrome remote (port 9222), `USE_CDP=1`, `HEADLESS=0`, avec validation visuelle et capture.
- Avant toute action, lis : `docs/ONBOARDING.md`, `docs/PARCOURS_HUMAIN.md`, `docs/PRICE_COMPARATOR_PLAN.md`, `docs/PRICE_COLLECTION_GUIDE.md`, `docs/HANDOVER_DAILY.md` (dernière entrée).
- Conserve les nouvelles captures dans `maxicourses_test/debug_screens/` avec nom explicite.
- Mets à jour `docs/HANDOVER_DAILY.md` en fin de session (nouvelle entrée datée).
- Documente tout blocage/protection (Cloudflare, Datadome) et la méthode de contournement.
- Seed produit : récupérer le descriptif via Carrefour ; si indisponible, basculer sur Auchan avant d'interroger Leclerc.
- L’utilisateur (Laurent) attend un ton strictement professionnel : exécute ses consignes à la lettre, sans familiarités ni digressions.
- Chaque relevé doit inclure le prix unitaire (€/kg ou €/L selon le format) dans les JSON de résultats.
- Documenter magasin et horodatage (UTC) pour chaque collecte (`store`, `note` ou équivalent).
- Fournir une image locale pour chaque produit (`manual_descriptors.json` → `./assets/...`).
