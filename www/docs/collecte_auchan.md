# Bible de la Collecte Auchan (SOP) - Version "Chaîne de Confiance"
> Dernière mise à jour : 07/12/2025

Ce document est la **garantie de fonctionnement**. Il détaille la configuration EXACTE requise, du serveur jusqu'au clic de souris. Si un seul maillon est brisé, la collecte échouera.

---

## 1. La Chaîne de Validation (Chain of Custody)

Pour qu'une collecte fonctionne, le flux d'exécution doit suivre ce chemin **sans interférence** :

1.  **Client (API)** : Envoie `POST /api/collect` à `server.py`.
2.  **Serveur (`server.py`)** : Reçoit la requête, prépare l'environnement.
    *   **CRITIQUE** : Doit injecter `CDP_URL="http://127.0.0.1:9223"` dans les variables d'environnement du sous-processus.
3.  **Pipeline (`run_pipeline.py`)** : Est lancé par le serveur.
    *   **CRITIQUE** : Doit transmettre l'environnement (dont `CDP_URL`) au script final.
4.  **Collecteur (`fetch_auchan_price.py`)** : Le script final.
    *   **CRITIQUE 1** : Ne doit JAMAIS créer de nouveau contexte (`make_context`).
    *   **CRITIQUE 2** : Doit se connecter au navigateur existant via `connect_over_cdp(env["CDP_URL"])`.
    *   **CRITIQUE 3** : Doit simuler un comportement humain (Random Click + Latence).

---

## 2. Validation Par Fichier : Points de Contrôle

Utilisez ces vérifications pour auditer votre code.

### A. Fichier : `www/maxicourses_test/server.py`
**Rôle** : Chef d'orchestre. Il ne doit jamais "oublier" de dire aux scripts où se trouve le navigateur.

*   **Contrôle Logic #1 : Injection Forcée du Tunnel CDP**
    *   *Pourquoi ?* Si absent, le script tentera d'ouvrir un Chrome local (headless) et se fera bloquer.
    *   *Le code doit contenir :*
    ```python
    env = os.environ.copy()
    env["USE_CDP"] = "1"
    if "CDP_URL" not in env:
        env["CDP_URL"] = "http://127.0.0.1:9223"  # <-- LIGNE VITALE
    ```
*   **Contrôle Logic #2 : Panneau de Contrôle Robuste (Async Restart)**
    *   *Pourquoi ?* Pour pouvoir redémarrer le serveur depuis l'interface web sans crash réseau.
    *   *Le code doit contenir :*
    ```python
    # Utilisation de Popen + nohup + sleep pour ne pas tuer le processus avant la réponse HTTP
    subprocess.Popen("nohup sh -c 'sleep 1; sudo systemctl restart maxicourses-web.service' ...")
    ```

### B. Fichier : `www/maxicourses_test/fetch_auchan_price.py`
**Rôle** : L'exécutant. Il doit être "propre" (Clean) et "malin" (Human).

*   **Contrôle Logic #1 : Connexion CDP Pure (Pas de Stealth)**
    *   *Interdit* : `scraper.engine.make_context(...)` (Injecte `playwright-stealth` = DÉTECTÉ).
    *   *Obligatoire* :
    ```python
    # Connexion directe au navigateur "humain" via le tunnel
    browser = await playwright.chromium.connect_over_cdp(cdp_url)
    context = browser.contexts[0] # Récupère la session ouverte
    await context.clear_cookies() # Nettoyage pré-session
    ```

*   **Contrôle Logic #2 : Clic Humain Randomisé**
    *   *Pourquoi ?* Un clic parfait au centre (x=50%, y=50%) est une signature de robot.
    *   *Le code doit contenir (fonction `choose_drive`) :*
    ```python
    # Calcul d'un offset aléatoire (+/- 5 pixels)
    offset_x = random.uniform(-5, 5)
    offset_y = random.uniform(-5, 5)
    
    # Mouvement souris + Délais variables
    await page.mouse.move(target_x, target_y)
    await page.wait_for_timeout(random.randint(150, 300))
    await page.mouse.down()
    await page.wait_for_timeout(random.randint(80, 150))
    await page.mouse.up()
    ```

*   **Contrôle Logic #3 : Cycle de Vie "Toast"**
    *   *Règle* : Auchan confirme le magasin par un popup "C'est noté". Si on n'attend pas sa disparition, la navigation suivante échoue (store non persisté).
    ```python
    await toast.wait_for(state="visible", timeout=3000)
    await toast.wait_for(state="hidden", timeout=15000)
    ```

---

## 3. Procédure de Mise en Production (Déploiement)

Un code correct en local ne sert à rien si le serveur OVH exécute une vieille version.

**La Règle d'Or du Déploiement :**
Si vous modifiez UN fichier Python en local (`/Users/laurentpoupet/...`), vous DEVEZ :

1.  **Synchroniser** : Lancer le script de déploiement.
    ```bash
    ./deploy_ovh.sh
    ```
2.  **Redémarrer le backend** : Pour recharger le code Python en mémoire.
    *   Via Terminal : `ssh ovh-server "sudo systemctl restart maxicourses-web.service"`
    *   OU Via Web : `https://api.maxicourses.fr/ovh_control` -> Bouton "Redémarrer".

---

## 4. Checklist de Debug "En Cas de Panne"

Si la collecte ne fonctionne plus, cochez ces cases dans l'ordre :

1.  [ ] **Tunnel SSH** : Le tunnel est-il actif ? (`ssh -R 9223:localhost:9222 ...`)
2.  [ ] **Chrome Local** : Votre Chrome Mac (port 9222) est-il ouvert ?
3.  [ ] **CDP_URL** : Le serveur envoie-t-il bien `http://127.0.0.1:9223` ? (Vérifier `server.py`)
4.  [ ] **Anti-Virus** : Avez-vous réactivé par erreur `playwright-stealth` ? (Vérifier `fetch_auchan_price.py`)
5.  [ ] **Déploiement** : Avez-vous oublié de faire `./deploy_ovh.sh` après la dernière modif ?

---

Ce document est la vérité technique du projet. Ne déviez pas de ces principes sans une raison majeure.
