# Rappel descriptif de Maxicourses.fr et Maxicourses APP
Ok, nous allons donc lancer le site MaxiCourse. Le projet est de mettre en place un comparateur de prix pour les enseignes de la grande distribution, par exemple Carrefour, Leclerc, Auchan, Intermarché, courseU, G20, chronodrive, Colruyt, Lidl, Aldi, Picard, et plein d'autres à la suite. Aujourd'hui ce que nous allons mettre en place c'est un proof of concept, c'est à dire à démontrer que le système fonctionne. Le principe de MaxiCourse c'est in fine, d'avoir la possibilité de scanner avec son iPhone un code-barre, de l'envoyer sur un serveur, ensuite à partir de ce serveur on va checker le descriptif du produit, ensuite comparer les prix sur les différentes plateformes. Une fois qu'on a le descriptif, on a le code-barre, on a le descriptif, donc on peut aller chercher sur toutes les plateformes

LIRE TOUS LES FICHIERS dans "docs"

Trouver le bug de collecte solo et global à partir de index2.html et trouver les bugs de collecte chez leclerc! pourquoi la collecte solo est differente de la collecte globale? il faut impérativement que la collecte solo récupère les meme mots cles que pour la collecte globale (mots cles magasin seed) lire les fichiers PRICE_COLLECTION_GUIDE.md seed_catalog.py

ce que je veux c'est que chaque collecte globale stock dans une bdd les mots cles seed afin qu'ils soient utilisés pour les collectes solo et dans cette meme bdd il faut que l'on stock les liens direct des magasins pour chaque produit afin de pouvoir lancer des collectes de prix uniquement pour faire des comparaison de prix dans le temps! et indiquer également la disponibilité du produit à un instant T
J'ai ajouté un bouton dans index2.html "MàJ prix" qui doit récupérer les liens des produits pour chaques magasins dans le fichier "descriptor_cache.json" mais ca ne fonctionne pas ! Ca lance une collecte classique au lieu d'aller directement sur les pages produit et récupérer les prix! Voila la priorité aujourd'hui mettre en place la possibilité de mettre à jour les prix des produits par magasin afin d'informer les utilisateur des fluctuations de prix !



Imperatif de nettoyer les fichiers de Maxicourses pour avoir un directory propre avec uniquement les fichiers utiles pour le fonctionnement de maxicourses afin de préparer proprement le developpement "DOCKER" de Maxicourses pour le déployer le moment venu sur le serveur OVH toutes les informations necessaires sont dans le fichier : OVH_SERVER_SETUP.md 

Empécher l'utilisation des mot cles de quantité poids volume etc... pour les recherche chez MONOPRIX !

Interdire les recherche direct avec EAN chez LECLERC !

Trouver le bug qui empèche de retirer une fiche produit du listing de index2.html

Creer un fichier qui stock les liens direct des magasins pour chaque produit afin de pouvoir lancer des collectes de prix uniquement pour faire des comparaison de prix dans le temps! et indiquer également la disponibilité du produit à un instant T




Maxicourses fonctionne en local uniquement pour le moment! il n'y a pas de maxicourses distant pour le moment sur ovh
