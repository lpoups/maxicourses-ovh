# MANIFESTE TECHNIQUE & PRODUIT MAXICOURSES
> *Document de référence : Vision, Architecture et Règles d'Or.*

## 1. La Vision Produit (Le "Pourquoi")
MaxiCourse est un **comparateur de prix de combat** pour la grande distribution française (GSA).
L'objectif est double et séquentiel :
1.  **L'Exactitude (B2B/B2C)** : L'utilisateur scanne un EAN -> On lui donne le prix de *ce* produit exact dans tous les magasins. Si on n'a pas l'info, on ne l'invente pas.
2.  **L'Intelligence (Le "Game Changer")** : Proposer l'alternative la moins chère ("Smart Substitution").
    *   *Exemple* : Je scanne du Coca-Cola 1.75L (2.50€). L'app me dit : "Chez Leclerc, le Bryce Cola équivalent est à 1.25€".
    *   C'est la mission ultime : faire économiser de l'argent sur le "besoin" (Cola) plutôt que juste sur la "marque" (Coca).

## 2. Le Moteur de Collecte (L'Architecture "Hybride")
Le système repose sur une distinction stricte entre deux types de sources de données.

### A. Les Sources de Vérité ("Seed Stores")
*Magasins permettant une recherche directe et fiable par EAN.*
*   **Rôle** : Fournir les données "Golden" (Titre, Marque, Poids, Image, Mots-clés).
*   **Enseignes** : Carrefour (Market/City/Super/Hyper), Auchan, Chronodrive, Courses U, G20.
*   **Règle** : Si l'EAN répond, c'est une vérité absolue. On extrait tout le jus (mots-clés descriptifs) pour nourrir le "Cerveau".

### B. Les Chasseurs ("Keyword Stores")
*Magasins nécessitant une recherche par mots-clés (pas de recherche EAN fiable).*
*   **Enseignes** : Leclerc, Monoprix, Intermarché, Casino, Spar, Lidl, Aldi.
*   **Défi** : Trouver le *bon* produit dans une botte de foin de résultats, souvent délibérément obfusqués.
*   **Stratégie** :
    1.  **Intermarché / Casino / Spar** : Recherche mots-clés -> Validation facile car l'EAN est visible dans le lien/page.
    2.  **Leclerc / Monoprix (Hard Mode)** :
        *   Recherche : Utiliser les mots-clés des "Seed Stores". Stratégie d'entonnoir (Large -> Précis si trop de résultats).
        *   Validation : Pas d'EAN fiable. **Impératif d'utiliser la VISION (IA)** pour comparer l'image du candidat avec l'image "Seed". C'est le seul juge de paix.

## 3. Le Cerveau (L'Intelligence Artificielle)
L'IA n'est pas un gadget, c'est le pilote nécessaire pour contrer l'obfuscation des distributeurs.
*   **Mission 1 (Texte)** : Comprendre les descriptifs hétérogènes. "Coca Original" = "Soda Cola Classique". Extraire les attributs (Goût, Volume, Unité).
*   **Mission 2 (Vision)** : Regarder les images comme un humain. Confirmer que le paquet de "Leclerc" est bien le même que celui de "Carrefour" (Matching Visuel).
*   **Mission 3 (Substitution)** : Identifier les produits équivalents (même catégorie, même volume, prix inférieur) pour la feature "Smart Substitution".

## 4. La Mémoire (La Base de Données)
*   **Infrastructure** : MongoDB sur Serveur OVH (À faire).
*   **Rôle** : Stocker le "Golden Record" de chaque EAN.
*   **Contenu** :
    *   EAN.
    *   Mots-clés validés (venant UNIQUEMENT de magasins exploités et vérifiés).
    *   Images de référence.
    *   Historique des prix.
    *   Liens directs par magasin (pour la mise à jour ultra-rapide).

## 5. Les Règles d'Or (Dogmes)
1.  **Zéro Hallucination** : Les mots-clés de recherche ne proviennent QUE des magasins seed ou de validations à 100%. Pas d'OpenFoodFacts, pas de dictionnaire externe douteux.
2.  **Validation Visuelle** : Sur les magasins "aveugles" (Leclerc/Monoprix), si on a un doute, on compare les images. Si l'IA visuelle dit "Non", on jette.
3.  **Transparence** : Si je (l'IA Tech) ne comprends pas une *finalité* produit, je demande au Product Owner (Vous). Je ne code pas au hasard.

## 6. Roadmap Immédiate (Le Plan de Bataille)
1.  **Fiabiliser le "Finder"** (Fait ✅) : S'assurer qu'on récupère bien les données Seed (Carrefour/Auchan/G20/CHRONODRIVE/COURSEU).
2.  **Construire la Mémoire (DB)** : Installer/Configurer MongoDB sur OVH pour ne plus perdre ces données.
3.  **Armer les Chasseurs** : Coder la logique "Recherche Large -> Affinage" + "Validation Visuelle" pour Leclerc/Monoprix.
4.  **L'interface "Smart"** : Préparer le terrain pour la substitution (Step 2 du projet).
