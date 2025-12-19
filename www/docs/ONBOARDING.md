# Rappel descriptif de Maxicourses.fr et Maxicourses APP
Ok, nous allons donc lancer le site MaxiCourse. Le projet est de mettre en place un comparateur de prix pour les enseignes de la grande distribution, par exemple Carrefour, Leclerc, Auchan, Intermarché, courseU, G20, chronodrive, Colruyt, Lidl, Aldi, Picard, et plein d'autres à la suite. Aujourd'hui ce que nous allons mettre en place c'est un proof of concept, c'est à dire à démontrer que le système fonctionne. Le principe de MaxiCourse c'est in fine, d'avoir la possibilité de scanner avec son iPhone un code-barre, de l'envoyer sur un serveur, ensuite à partir de ce serveur on va checker le descriptif du produit, ensuite comparer les prix sur les différentes plateformes. Une fois qu'on a le descriptif, on a le code-barre, on a le descriptif, donc on peut aller chercher sur toutes les plateformes

LIRE le fichier : 

LIRE TOUS LES FICHIERS dans "docs"

les fichiers de maxicourses ovh se trouve dans maxicourses-ovh

Lire le fichier MIGRATION_OVH.md

# IMPORTANT!!!
ajouter ICI toutes les informations pour la maintenance et le fonctionnement de maxicourses sur le serveur OVH comment il fonctionne ce qu'il faut savoir pour les prochains GPT!!!


# à partir de maintenant maxicourses.fr fonctionne à partir du serveur OVH page accueil : http://api.maxicourses.fr/index.html toutes les information de connexion 
sont disponibles dans le fichier : OVH_SERVER_SETUP.md

Bien s'assurer que c'est bien "chrome debug 9222" qui est installé sur le serveur OVH et pas "chromium"

Trouver les bugs de collecte chez leclerc! 

TODO
Corriger le bug de collecte de courseu (Cloudflare) faire un reset de cookies et de cache avant de relancer la collecte cela fonctionne tres bien lorsque la collecte est lancée par gemini mais pas lorsque la collecte est lancée par le bouton collecte solo ou globale.

Corriger le bug de collete de lerclerc : Les mots cles de recherche sont excellent mais lors du resultat de recherche aucun produit n'est selectionné et de nouveau mots cles de recherche et toujours pareil aucun produit n'est selectionné alors que le bon produit est présent dans la liste de resultat à chaque recherche. Cela prouve que la selection des mots cles est bonne mais le robot ne fait pas le travail!

## Mode « MàJ prix » (collecte rapide)
- L'API `/api/update-price` force maintenant `USE_CACHED_URLS=1` et chaque fetcher compatible consomme les URLs enregistrées dans `maxicourses_test/pipeline/descriptor_cache.json` (`<enseigne>_url`).
- Les scripts Carrefour (City/Market/Super), Auchan, Chronodrive, Course U, G20, Casino/Spar, Intermarché et Monoprix sautent totalement la phase de recherche dès qu’un `DIRECT_URL` est fourni. Ils chargent directement la PDP puis extraient prix, prix unitaire et quantité.
- Si l’URL directe échoue et que `SKIP_SEARCH` (envoyé automatiquement par le bouton) est à `true`, l’adaptateur renvoie immédiatement `NO_PRICE`/`NO_MATCH` sans relancer une collecte complète. Sans ce flag, le fetcher retombe sur la procédure normale.
- L’UI `http://api.maxicourses.fr/index.html` actualise ensuite le dataset ciblé sans repasser par `run_pipeline.py` complet. La table magasins affiche aussi une colonne « Prix date » avec l’horodatage courant + l’ancien prix pour suivre les écarts.
- Cas particuliers : Leclerc Drive reste en mode manuel (pas d’accès direct fiable) et continuera d’utiliser `manual_leclerc_cdp.py` même en « MàJ prix ». Documenter toute relance dans `HANDOVER_DAILY.md`.

la base de données MongoDB est la base de données de maxicourses toutes les informations sont maintenant stockées dans la bdd ! plus aucun json ou autres fichier ne traite les données de fiche produits données de collecte etc. 

Mettre en place la cle API gemini 3 à la place de la cle api openai qui est dans le fichier "openai_key.md"






