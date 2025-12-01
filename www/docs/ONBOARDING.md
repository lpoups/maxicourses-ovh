# Rappel descriptif de Maxicourses.fr et Maxicourses APP
Ok, nous allons donc lancer le site MaxiCourse. Le projet est de mettre en place un comparateur de prix pour les enseignes de la grande distribution, par exemple Carrefour, Leclerc, Auchan, Intermarché, courseU, G20, chronodrive, Colruyt, Lidl, Aldi, Picard, et plein d'autres à la suite. Aujourd'hui ce que nous allons mettre en place c'est un proof of concept, c'est à dire à démontrer que le système fonctionne. Le principe de MaxiCourse c'est in fine, d'avoir la possibilité de scanner avec son iPhone un code-barre, de l'envoyer sur un serveur, ensuite à partir de ce serveur on va checker le descriptif du produit, ensuite comparer les prix sur les différentes plateformes. Une fois qu'on a le descriptif, on a le code-barre, on a le descriptif, donc on peut aller chercher sur toutes les plateformes

LIRE TOUS LES FICHIERS dans "docs"

Trouver le bug de collecte solo et global à partir de index2.html et trouver les bugs de collecte chez leclerc! pourquoi la collecte solo est differente de la collecte globale? il faut impérativement que la collecte solo récupère les meme mots cles que pour la collecte globale (mots cles magasin seed) lire les fichiers PRICE_COLLECTION_GUIDE.md seed_catalog.py

ce que je veux c'est que chaque collecte globale stock dans une bdd les mots cles seed afin qu'ils soient utilisés pour les collectes solo et dans cette meme bdd il faut que l'on stock les liens direct des magasins pour chaque produit afin de pouvoir lancer des collectes de prix uniquement pour faire des comparaison de prix dans le temps! et indiquer également la disponibilité du produit à un instant T
J'ai ajouté un bouton dans index2.html "MàJ prix" qui doit récupérer les liens des produits pour chaques magasins dans le fichier "descriptor_cache.json" mais ca ne fonctionne pas ! Ca lance une collecte classique au lieu d'aller directement sur les pages produit et récupérer les prix! Voila la priorité aujourd'hui mettre en place la possibilité de mettre à jour les prix des produits par magasin afin d'informer les utilisateur des fluctuations de prix !

## Mode « MàJ prix » (collecte rapide)
- L'API `/api/update-price` force maintenant `USE_CACHED_URLS=1` et chaque fetcher compatible consomme les URLs enregistrées dans `maxicourses_test/pipeline/descriptor_cache.json` (`<enseigne>_url`).
- Les scripts Carrefour (City/Market/Super), Auchan, Chronodrive, Course U, G20, Casino/Spar, Intermarché et Monoprix sautent totalement la phase de recherche dès qu’un `DIRECT_URL` est fourni. Ils chargent directement la PDP puis extraient prix, prix unitaire et quantité.
- Si l’URL directe échoue et que `SKIP_SEARCH` (envoyé automatiquement par le bouton) est à `true`, l’adaptateur renvoie immédiatement `NO_PRICE`/`NO_MATCH` sans relancer une collecte complète. Sans ce flag, le fetcher retombe sur la procédure normale.
- L’UI `index2.html` actualise ensuite le dataset ciblé sans repasser par `run_pipeline.py` complet. La table magasins affiche aussi une colonne « Prix date » avec l’horodatage courant + l’ancien prix pour suivre les écarts.
- Cas particuliers : Leclerc Drive reste en mode manuel (pas d’accès direct fiable) et continuera d’utiliser `manual_leclerc_cdp.py` même en « MàJ prix ». Documenter toute relance dans `HANDOVER_DAILY.md`.

### TODO MàJ prix / suivi collectes
- **Procédure standard à chaque test** :
  1. `pkill -f chrome && maxicourses_test/start_chrome_debug.sh` pour repartir d’un profil sain et éviter les anti-bot.
  2. Vérifier que `maxicourses_test/pipeline/descriptor_cache.json` contient bien l’entrée `<EAN>` avec tous les champs `carrefour_*_url`, `auchan_url`, `chronodrive_url`, `courseu_url`, `casino_url`, `spar_url`, `intermarche_url`, `monoprix_url`, etc. (sinon re-souder le lien PDP depuis le dernier seed).
  3. Lancer `curl -X POST http://127.0.0.1:5001/api/update-price -d '{"ean":"<EAN>"}'` puis contrôler les JSON `results/test-<EAN>/{latest,summary}.json` avant de regarder `pipeline/index2.html`.
- **Alimentation du cache** : après chaque collecte globale (`run_pipeline.py`), fusionner les URLs PDP confirmées dans `descriptor_cache.json`. Ce fichier est la seule source utilisée par le bouton, donc aucune enseigne n’est rafraîchie si `*_url` est manquant ou obsolète.
- **Contrôles par enseigne** :
  - *Carrefour/Auchan/Chronodrive/Course U* : s’assurer que la state CDP reste valide (FRONTAL_STORE, slug drive). Toute bannière Cloudflare ⇒ relancer `save_state_from_cdp.py` avant la prochaine MàJ.
  - *Casino/Spar* : confirmer que le HTML `.prixProduit` est bien parsé (prix pack + €/kg). Si `unit_price` est vide dans `latest.json`, recharger la PDP et ajuster le fetcher avant de publier les chiffres.
  - *Intermarché* : vérifier que la double sélection magasin + recherche texte fonctionne encore. Si `DIRECT_URL` tombe sur une 404, relancer la recherche manuelle pour rafraîchir `intermarche_url`.
  - *Monoprix* : la MàJ repose sur l’image + tokens seed. Toujours fournir un screenshot et confirmer que la variante détectée correspond au seed, sinon corriger `seed_catalog.py`.
  - *Leclerc* : pas d’automatisation. Rejouer `manual_leclerc_cdp.py`, noter l’heure Europe/Paris dans `HANDOVER_DAILY.md` et archiver les captures si DataDome bloque.
- **Validation UI** : après chaque MàJ, ouvrir `pipeline/index2.html`, vérifier la colonne « Prix date » (dernière collecte + ancien prix) et s’assurer que le badge “TOP PRIX” correspond au *prix pack* (si une enseigne n’a qu’un prix unitaire, corriger le fetcher).
- S’assurer que chaque collecte globale alimente `maxicourses_test/pipeline/descriptor_cache.json` avec les URLs PDP validées pour toutes les enseignes (sinon le bouton n’a rien à rejouer).
- Avant chaque test (collecte ou MàJ prix), redémarrer Chrome debug (`maxicourses_test/start_chrome_debug.sh`) pour repartir d’un profil propre et éviter les blocages anti-bot.
- Leclerc : la MàJ reste 100 % manuelle. Préparer la trace CDP, documenter les plantages éventuels et noter les horaires dans `docs/HANDOVER_DAILY.md`.
- Casino/Spar : vérifier que les prix/quantités récupérés correspondent bien aux montants affichés sur les PDP. En cas d’écart, relancer la MàJ prix et contrôler que `price` **et** `unit_price` sont présents dans `results/test-<EAN>/latest.json` avant de diffuser l’information.



Imperatif de nettoyer les fichiers de Maxicourses pour avoir un directory propre avec uniquement les fichiers utiles pour le fonctionnement de maxicourses afin de préparer proprement le developpement "DOCKER" de Maxicourses pour le déployer le moment venu sur le serveur OVH toutes les informations necessaires sont dans le fichier : OVH_SERVER_SETUP.md 

Empécher l'utilisation des mot cles de quantité poids volume etc... pour les recherche chez MONOPRIX !

Interdire les recherche direct avec EAN chez LECLERC !

Trouver le bug qui empèche de retirer une fiche produit du listing de index2.html

Creer un fichier qui stock les liens direct des magasins pour chaque produit afin de pouvoir lancer des collectes de prix uniquement pour faire des comparaison de prix dans le temps! et indiquer également la disponibilité du produit à un instant T




Maxicourses fonctionne en local uniquement pour le moment! il n'y a pas de maxicourses distant pour le moment sur ovh
