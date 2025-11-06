# Règles Seed & Mots-clés

Ce mémo doit être mis à jour après chaque collecte. Pour chaque EAN : consigner les erreurs à éviter et la méthode validée.

⚠️ **Règle globale** : plus aucun mot-clé n’est maintenu dans des fichiers `.json`. Toute évolution passe par `finder.py`, `KeywordGenerator` ou `seed_catalog.py`. Toute tentative de recréer des `.json` de mots-clés est interdite et doit être refusée.

## 3700260216148 – Croquettes chat saumon ULTIMA 1,5 kg
- **Faire ceci = erreur**
  - Utiliser la fiche Chronodrive (renvoie Purina 3 kg, `matched_ean` vide).
  - Injecter `stérilisé`/`adulte` dans la requête primaire (garder ces termes en validation secondaire seulement).
- **Faire cela = OK**
  - Seeds : Carrefour Market OK, Carrefour City `NO_PRICE`, Auchan `NO_RESULTS`.
  - Requête primaire : `ULTIMA 1.5kg chat croquettes` (variantes autorisées : `ULTIMA Croquettes Chat Saumon`, etc.).
  - Secondaires à vérifier dans le listing : `saumon`, `adulte`, `stérilisé`.

## 8712100731822 – Moutarde Savora 385 g
- **Faire ceci = erreur**
  - Oublier la variante « aromates » (indispensable pour filtrer les produits classiques Amora).
  - Mélanger une orthographe erronée (ex. « Amorates ») sans conserver la vraie variante `aromates`.
  - Valider la fiche Chronodrive « Moutarde de Dijon forte 430 g » (`matched_ean` vide, format différent).
- **Faire cela = OK**
  - Seeds : Carrefour Market + City OK (matched EAN). Auchan `NO_RESULTS`.
  - Requête primaire : `Amora 385g moutarde` (variantes : `Amora Moutarde Savora 385g`, etc.).
  - Secondaires : `aromates`, `amorates` (forme Carrefour), `epices`, `savora`.

## 8700216698191 – Lessive capsules ARIEL Grandiose 21
- **Faire ceci = erreur**
  - Requête type « capsules Original » sans préciser le volume (21 capsules) → génère des packs x50.
  - Fermer les yeux sur la mention « Grandiose »/« Original » (permet de filtrer le bon parfum).
- **Faire cela = OK**
  - Seeds : Carrefour Market OK, City `NO_PRICE`, Auchan `NO_RESULTS`.
  - Requête primaire : `ARIEL 21 capsules lessive` (variantes : `ARIEL Lessive capsules`, `ARIEL Original ARIEL capsules`).
  - Secondaires : `grandiose`, `original`, `ariel`.

(Compléter cette liste à chaque nouveau produit.)

## 5000112611861 – Coca‑Cola 1,75 L (bouteille)
- Faire ceci = erreur
  - Accepter des cartes contenant `6x20cl`, `pack`, `lot`, `mini` (Monoprix/Intermarché renvoient souvent ces lots).
  - Utiliser `soda`/`boisson` dans la requête primaire (non discriminant et consomme la limite de 30 car.).
  - Chercher `1.75` sans variantes (`1,75`, `175`) → moteurs stricts.
- Faire cela = OK
  - Requête primaire (≤30 car.) : `Coca-Cola 1,75L`, `Coca 1,75L`, `Coca-Cola original 1,75`.
  - Secondaires obligatoires sur carte/PDP : `coca-cola`, `original`, `1,75L` (variants acceptées : `1.75`, `175`).
  - Bannir cartes avec motifs multiplicateurs (`\d+\s*[x×]\s*\d+`) et mots `pack/lot/mini`.
  - Sur PDP : confirmer contenance exacte (`1,75 L`) et cohérence image/texte (bouteille unique).

## 3502110008329 – Soda cola PEPSI 1,5 L
- **Faire ceci = erreur**
  - Utiliser la fiche Chronodrive « Pepsi Max Zéro 4 x 1,5 L » (`matched_ean` vide, pack multiple).
- **Faire cela = OK**
  - Seeds : Auchan OK, Carrefour Market/City `NO_PRICE`.
  - Requête primaire : `Pepsi 1,5L cola` (variantes : `Pepsi cola 1,5`, `Pepsi 1,5`).
  - Secondaires : `pepsi`, `cola`, `1,5l`, `1,5`, `150cl`.

## 3665468000312 – Déboucheur Destop 950 ml
- **Faire ceci = erreur**
  - Valider la fiche Chronodrive « Gel javel entretien canalisations 750 ml » (`matched_ean` absent, volume incorrect).
- **Faire cela = OK**
  - Seeds : Carrefour Market OK, City OK.
  - Requête primaire : `Destop déboucheur original 950ml` (variantes `Destop original 950ml`, `Destop déboucheur liquide original`).
  - Matching final : uniquement via l’image (hash sur l’asset local `pipeline/assets/3665468000312.jpg`) ; le texte n’est plus filtrant.

## 3017760821375 – (DESCRIPTEUR À TROUVER)
- **Faire ceci = erreur**
  - Sauter la collecte seed Carrefour/Auchan : les scripts retournent `NO_PRICE`/`NO_RESULTS`. Tant que la fiche n’est pas trouvée, ne pas lancer les fetchers texte.
  - Injecter manuellement un descriptif générique dans `seed_catalog.py`.
- **Faire cela = OK**
  - Relancer Carrefour Market → City → Auchan avec l’EAN brut dès qu’un magasin référence le produit.
  - Documenter l’échec dans le handover tant qu’aucune enseigne seed ne connaît l’article.

## 3222472129798 – (DESCRIPTEUR À TROUVER)
- **Faire ceci = erreur**
  - Tenter les fetchers texte sans seed validé (Aucun drive ne retourne l’EAN).
  - Conserver des champs `*_queries` obsolètes dans le descripteur.
- **Faire cela = OK**
  - Réessayer ponctuellement Carrefour/Auchan/Chronodrive pour détecter l’apparition de la fiche.
  - Noter explicitement dans le handover que l’EAN reste introuvable.

## 5449000000996 – Coca-Cola 33 cl (canette)
- **Faire ceci = erreur**
  - Lancer la boucle IA alors qu’aucun seed Carrefour/Auchan n’a été obtenu (toutes les tentatives 2025-10-08 → `NO_PRICE`/`EMPTY_STDOUT`).
- **Faire cela = OK**
  - Prévoir une nouvelle tentative seed lorsqu’une enseigne référence de nouveau la canette. Tant que le seed est absent, laisser `primary/secondary` vides.

## 69588535 – EAN incomplet
- **Faire ceci = erreur**
  - Essayer d’enrichir un EAN à 8 chiffres : le pipeline rejette l’entrée (`EAN invalide : 69588535`).
- **Faire cela = OK**
  - Retirer ou compléter l’EAN (doit être sur 13 chiffres) avant toute relance.

## 8718951705876 – Sanex Derma Thérapie
- **Faire ceci = erreur**
  - Considérer le seed Chronodrive/Auchan comme valide alors qu’ils renvoient `EMPTY_STDOUT` / `NO_PRICE`.
  - Lancer les fetchers texte sans descriptif fiable : entraîne des `EMPTY_STDOUT` (voir logs et erreur `TargetClosedError` côté Leclerc).
- **Faire cela = OK**
  - Réessayer Carrefour lorsque le produit reviendra au catalogue.
  - Documenter dans le handover que l’EAN est temporairement indisponible (Carrefour Market/City => `NO_PRICE` le 2025-10-08).

## 5010029229110 – Weetabix Crispy Minis Chocolat
- **Faire ceci = erreur**
  - Conserver les anciennes requêtes AI (`*_ai_queries`) alors que les seeds Carrefour/Auchan retournent `NO_PRICE`.
- **Faire cela = OK**
  - Attendre un seed Carrefour/Auchan avant de regénérer les mots-clés primaires/secondaires.

## 1234567890123 – EAN factice
- **Faire ceci = erreur**
  - Traiter cette entrée comme un produit réel : aucun drive n’accepte l’EAN.
- **Faire cela = OK**
  - Laisser l’entrée marquée `removed=true` et consigner qu’il s’agit d’un EAN de test.

## 3599741007593 – Frites surgelées (OpenFoodFacts)
- **Faire ceci = erreur**
  - Lancer IA/fetchers sans seed : Carrefour Market/City → `NO_PRICE`, Auchan → `NO_RESULTS`.
- **Faire cela = OK**
  - Documenter l’absence de fiche et relancer périodiquement Carrefour/Auchan.
