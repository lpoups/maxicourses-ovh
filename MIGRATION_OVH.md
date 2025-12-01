# Migration Maxicourses vers OVH

alors la mission est de déployer maxicourses sur le serveur ovh afin qu'il fonctionne de la meme facon qu'en local ! mais il est impératif que maxicourses en local fonctionne toujours parfaitement il est imperatif que le deploiement sur ovh n'empeche en rien le fonctionnement de maxicourses en local! certaines choses ont déja ete faite pour cela sur le serveur ovh les information sont dans "OVH_SERVER_SETUP.md" mais tu peux décider de repartir de zero ti tu le souhaites! le plus important est que maxicourses local ne soit absolument pas touché car je m'en sers pour faire mes demonstrations pour les futurs investisseurs! quel plan me proposes tu? je ne veux que soit copié sur maxicourses ovh que les fichiers necessaires au fonctionnement de maxicourses ovh et bien entendu les "docs" les donnes de connexion sftp sont dans le fichier www/.vscode/sftp.json Il est impératif que tout se passe parfaitement ! et tu dois également prendre en compte ma limitation de token ici et donc alimenter constament un fichier "MIGRATION_OVH.md" pour que le prochain Gemini ou Claude ou GPT puisse continuer le travail en ayant connaissance de tout ce qui a ete fait et de tout ce qu'il reste à faire.

Ce document retrace toutes les étapes de la migration/déploiement de Maxicourses sur le serveur OVH. Il sert de référence pour les futures interventions.

## Objectif
Déployer Maxicourses sur le VPS OVH (`vps-a4a36a41.vps.ovh.net`) pour qu'il fonctionne de manière autonome, identique au local, sans impacter l'environnement local.

## État des lieux (Initial)
- **Local**: Fonctionnel. Dossier `~/Sites/maxicourses-ovh`.
- **Serveur**: VPS Ubuntu. Accès SSH configuré.
- **Documentation existante**: `www/docs/OVH_SERVER_SETUP.md`.
- **Contraintes**:
    - Ne pas toucher au local.
    - Copier uniquement les fichiers nécessaires.
    - Maintenir ce fichier à jour.

## Journal des modifications

### [Date: 2025-11-29] - Initialisation
- Analyse de la structure du projet.
- Création du plan de déploiement.
- Vérification de la connexion SSH.

#  creation des fichiers verify_remote.sh et update_service_foreground.sh et configure_service.sh et start_chrome_foreground.sh et deploy_ovh.sh et fix_service.sh

### [Date: 2025-11-29] - Configuration Services & Scripts
- Création de `deploy_ovh.sh` pour le rsync et setup venv.
- Création de `configure_services.sh` pour adapter et installer les services systemd.
- Création de `start_chrome_foreground.sh` pour lancer Chrome en avant-plan (meilleure gestion systemd).
- Mise à jour du service `chrome-debug@.service` pour utiliser le script foreground.
- Création de `run_pipeline_server.sh` (manquant localement) pour lancer la pipeline sur le serveur.
- Création de `verify_remote.sh` pour tester l'environnement distant.
- **État actuel**: Chrome tourne sur le port 9222. Test d'import Python en cours de debug (problème de PYTHONPATH).

### [Date: 2025-11-29] - Validation & Finalisation
- Correction du `PYTHONPATH` dans `verify_remote.sh`.
- **Validation réussie**:
    - Import des modules Python (`manual_leclerc_cdp`, `seed_catalog`) OK.
    - Connexion CDP à Chrome (port 9222) OK.
- Le déploiement est fonctionnel dans `~/maxicourses-ovh`.

## Utilisation
- **Lancer une collecte manuelle**:
  ```bash
  ssh ovh-server
  cd ~/maxicourses-ovh/www
  source .venv/bin/activate
  export USE_CDP=1
  export CDP_URL="http://127.0.0.1:9222"
  # Exemple
  python3 maxicourses_test/manual_leclerc_cdp.py
  ```
- **Services Systemd**:
  - `chrome-debug@ubuntu.service`: Gère Chrome headless.
  - `run-pipeline@<EAN>.service`: Lance une collecte pour un EAN.
  - `run-pipeline@<EAN>.timer`: Planifie la collecte.

## Prochaines étapes
- Surveiller les logs: `journalctl -u chrome-debug@ubuntu.service -f`.
- Activer les timers pour les produits souhaités.

## Interface Web (Miroir Local)
Pour accéder à l'interface web (identique à `index2.html` local) :

1. **Créer un tunnel SSH** (depuis votre machine locale) :
   ```bash
   ssh -L 5001:127.0.0.1:5001 ovh-server
   ```
   *Cela redirige le port 5001 de votre machine vers le port 5001 du serveur.*

2. **Ouvrir dans le navigateur** :
   [http://localhost:5001](http://localhost:5001)

3. **Fonctionnement** :
   - L'interface communique avec le serveur OVH via le tunnel.
   - Les collectes se lancent sur le serveur.
   - Les fichiers sont servis depuis `~/maxicourses-ovh/www/maxicourses_test/pipeline`.

### Détails techniques Web
- **Script serveur** : `server_ovh.py` (copie de `server.py` avec route `/` ajoutée).
- **Page HTML** : `index_ovh.html` (copie de `index2.html` avec `API_BASE` relatif).
- **Service** : `maxicourses-web.service` (port 5001).

## Accès Public (https://maxicourses.fr)
**Statut**: ✅ Opérationnel.

1. **Configuration VPS**:
   - Nginx installé et configuré (reverse proxy port 5001).
   - **Certificat SSL (HTTPS)** : Activé pour `api.maxicourses.fr`.

2. **Fichier Frontend**:
   - `index_ovh.html` sur l'hébergement mutualisé doit pointer vers `https://api.maxicourses.fr`.
   - Testé et validé.

## Dépannage & Commandes Utiles

### Gérer le serveur web (server_ovh.py)
- **Vérifier le statut** :
  ```bash
  sudo systemctl status maxicourses-web.service
  ```
  *(Doit afficher "Active: active (running)")*

- **Voir les logs en direct** :
  ```bash
  journalctl -u maxicourses-web.service -f
  ```
  *(Utile pour voir les erreurs pendant une collecte)*

- **Redémarrer le serveur** :
  ```bash
  sudo systemctl restart maxicourses-web.service
  ```

- **Arrêter le serveur** :
  ```bash
  sudo systemctl stop maxicourses-web.service
  ```

### Gérer Chrome (chrome-debug)
- **Vérifier le statut** :
  ```bash
  sudo systemctl status chrome-debug@ubuntu.service
  ```
- **Redémarrer Chrome** :
  ```bash
  sudo systemctl restart chrome-debug@ubuntu.service
  ```

### Problème d'images (404)
Si les images ne s'affichent pas, c'est que le serveur Python ne servait pas le dossier `/assets`.
- **Correctif appliqué** : Route `/assets/<path:filename>` ajoutée à `server_ovh.py`.
- **Vérification** : `curl -I https://api.maxicourses.fr/assets/logos/leclerc.png` doit renvoyer `200 OK`.

### Images de produits manquantes
**Cause** : Les images de produits (`.jpg`) sont générées **pendant les collectes** et stockées dans `results/test-<ean>/`.

**Solution appliquée** :
1. Synchronisation du dossier `results/` local vers OVH (~547MB).
   ```bash
   rsync -avz www/maxicourses_test/results/ ovh-server:~/maxicourses-ovh/www/maxicourses_test/results/
   ```
2. Les images s'affichent désormais car le serveur peut servir `/results/<ean>/`.

**Important** : Pour que les nouvelles collectes génèrent des images :
- Le serveur doit pouvoir écrire dans `~/maxicourses-ovh/www/maxicourses_test/results/`
- Les scripts de collecte doivent fonctionner correctement (voir section suivante)

### Collections qui échouent (timeout, cf block)
**Statut** : En cours de diagnostic.

Les erreurs suivantes peuvent apparaître :
- `timeout` : Le script de collecte prend trop de temps
- `cf block` : Cloudflare bloque la requête (détection de bot)
- `non dispo` : Produit indisponible dans ce magasin

**Images de produits (`.jpg` dans `assets/`)**:
- Téléchargées automatiquement par `ensure_local_image_asset()` pendant chaque collecte réussie
- Fonction dans `pipeline/run_pipeline.py` lignes 1055-1101
- Si échec silencieux (exception), pas d'image générée

**Diagnostic complet** : Voir [walkthrough.md](file:///Users/laurentpoupet/.gemini/antigravity/brain/bdc8c7c1-55d4-4218-828d-69272705dba6/walkthrough.md)

**Prochaines étapes** :
1. Tester une collecte manuelle sur OVH
2. Vérifier les logs en temps réel : `journalctl -u maxicourses-web.service -f`
3. Ajuster les timeouts si nécessaire

### Test de collecte manuel sur OVH
```bash
ssh ovh-server
cd ~/maxicourses-ovh/www/maxicourses_test  
source ../.venv/bin/activate
export USE_CDP=1
export CDP_URL="http://127.0.0.1:9222"

# Test Coca-Cola
python3 pipeline/run_pipeline.py --ean 5000112611861 --adapters carrefour_city

# Vérifier image générée
ls -lh assets/5000112611861.jpg
```

### RÉSOLUTION FINALE (2025-11-29 19:15)
✅ **Problème images produits résolu !**

**Bug identifié** :
- Ligne 32 de `pipeline/run_pipeline.py` : `ASSETS_DIR = ROOT_DIR / "pipeline" / "assets"`
- Les images étaient téléchargées dans `pipeline/assets/` au lieu de `assets/`

**Correctif appliqué** :
```python
# AVANT
ASSETS_DIR = ROOT_DIR / "pipeline" / "assets"

# APRÈS  
ASSETS_DIR = ROOT_DIR / "assets"
```

**Validation** :
```bash
# Test de collecte Auchan
python3 pipeline/run_pipeline.py --ean 5000112611861 --adapters auchan
# → Image téléchargée : assets/5000112611861.jpg (75KB)

# Test accès HTTPS
curl -I https://api.maxicourses.fr/assets/5000112611861.jpg
# → 200 OK, Content-Type: image/jpeg
```

### RÉSULTATS TESTS COLLECTES

| Adaptateur | Statut | Prix | Image | Notes |
|------------|--------|------|-------|-------|
| Auchan | ✅ OK | 2,39€ | ✅ Téléchargée | Fonctionne parfaitement |
| Chronodrive | ✅ OK | 2,49€ | ✅ Téléchargée | Fonctionne parfaitement |
| Leclerc | ✅ OK | 2,37€ | ✅ Téléchargée | Fonctionne parfaitement |
| Monoprix | ✅ OK | 2,45€ | ✅ Téléchargée | Fonctionne parfaitement |
| Carrefour | ❌ CF_BLOCK | - | - | Bloqué par Cloudflare |
| Intermarché | ❌ DATADOME | - | - | Bloqué par Datadome |

**Recommandations** :
1. Utiliser prioritairement Auchan, Intermarche, Monoprix pour les tests
2. Carrefour nécessite rotation d'IP ou proxy pour contourner Cloudflare
3. Leclerc à debugger séparément (vérifier config CDP)

### ⚠️ ANALYSE APPROFONDIE : BLOCAGE CARREFOUR (29/11/2025)

**Statut** : ❌ **IMPOSSIBLE sur IP Datacenter OVH**
**Objectif** : 100k requêtes/jour (Scalabilité requise)

#### 1. Diagnostic Technique
Cloudflare protège Carrefour avec un niveau de sécurité "Enterprise".
- **Détection IP** : L'IP du VPS (`91.134.133.156`) est identifiée comme "OVH SAS" (Datacenter).
- **Conséquence** : Blocage immédiat (Error 1020) ou Boucle de Challenge ("Un instant...") impossible à résoudre automatiquement.

#### 2. Tentatives de Contournement (Toutes Échouées)
Nous avons épuisé toutes les solutions logicielles possibles sur le serveur :

| Méthode Testée | Hypothèse | Résultat | Cause de l'échec |
|----------------|-----------|----------|------------------|
| **Playwright Stealth** | Masquer les variables JS d'automatisation | ❌ CF_BLOCK | L'IP est flaggée avant même l'exécution JS |
| **Mode Headed (Xvfb)** | Simuler un écran réel (1920x1080) | ❌ CF_BLOCK | Cloudflare ignore le mode d'affichage si l'IP est suspecte |
| **Injection Cookies** | Utiliser une session valide (Mac local) | ❌ CF_BLOCK | Les cookies sont invalidés dès que l'IP change (Geo-lock) |
| **Google Chrome Stable** | Utiliser la signature TLS officielle (v142) | ❌ CF_BLOCK | Confirme que ce n'est pas le navigateur qui est détecté, mais l'IP |
| **Résolution Challenge** | Mouvements souris + Attente | ❌ CF_BLOCK | Le challenge Turnstile détecte l'environnement serveur |

#### 3. La Seule Solution Viable : Proxies Résidentiels
Pour atteindre **100k requêtes/jour** sans blocage, il est impératif de masquer l'origine OVH.

**Recommandation Architecture :**
1. **Service de Proxy** : BrightData, Smartproxy ou Oxylabs.
2. **Configuration** : Rotation d'IPs résidentielles françaises à chaque requête.
3. **Coût estimé** : ~50-100€/mois pour démarrer, évolutif selon volume.

**Pourquoi c'est non-négociable :**
- Les contournements "gratuits" (cookies, user-agents) sont instables et ne tiendront jamais la charge de 100k/jour.
- Une app iPhone grand public ne peut pas dépendre d'une bidouille qui casse tous les 2 jours.

#### 4. Intermarché : Blocage Datadome (30/11/2025)
**Statut** : ❌ **IMPOSSIBLE sur IP Datacenter OVH**
**Protection** : Datadome (Geo-Captcha)
**Symptôme** : Page blanche avec script `captcha-delivery.com` et message "Please enable JS".
**Solution** : Idem Carrefour -> Proxy Résidentiel obligatoire.

### 5. Mode Hybride (Solution de contournement actuelle)
Pour contourner les blocages (Carrefour/Intermarché) sans payer de proxy, on utilise votre connexion Mac (IP Résidentielle) via un Tunnel SSH Inversé.

### 5. Mode Hybride Automatique (Dual-Port)
Cette configuration permet de lancer une collecte globale sans intervention humaine. Le système bascule automatiquement entre le Chrome du serveur (rapide) et votre Chrome local (résidentiel) selon le magasin.

**Architecture :**
- **Port 9222** : Chrome sur le serveur (Utilisé pour Auchan, Leclerc, Monoprix, etc.)
- **Port 9223** : Tunnel vers votre Mac (Utilisé pour Carrefour, Intermarché)

**Procédure de lancement (Une seule fois) :**
1. **Sur le Panel OVH** :
   - Assurez-vous que `Chrome Debug Service` est **LANCÉ** (Statut OK).
   - Assurez-vous que `Tunnel SSH` est **OK** (voir étape 3).

2. **Sur votre Mac (Terminal 1)** : Lancer Chrome en mode debug (Port 9222)
   ```bash
   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug
   ```

3. **Sur votre Mac (Terminal 2)** : Lancer le Tunnel sur le port **9223**
   ```bash
   ssh -R 9223:localhost:9222 ovh-server
   ```
   *(Notez le `9223` au début : cela mappe le port 9223 du serveur vers le 9222 de votre Mac)*

4. **Lancement de la collecte** :
   Lancez simplement votre collecte globale. Le script utilisera automatiquement le bon port.

---







## Plan de déploiement
1.  **Vérification Serveur**: État actuel, dépendances (Python, Chrome).
2.  **Script de Déploiement**: Création d'un script `deploy_ovh.sh` pour synchroniser les fichiers via `rsync` (exclusion des fichiers inutiles).
3.  **Configuration Environnement**: Création du venv Python sur le serveur, installation des requirements.
4.  **Configuration Services**: Mise en place des services systemd (Chrome headless, Pipeline).
5.  **Validation**: Test de fonctionnement sur le serveur.

### [Date: 2025-12-01] - Préparation app iOS & sauvegarde GitHub
- Objectif: ne rien changer sur OVH, préparer une app iOS qui scanne un code-barres et l'envoie à `api.maxicourses.fr`.
- Sauvegarde GitHub: branch `backup-ovh-20251201` poussée sur `https://github.com/lpoups/maxicourses-ovh` (copie lecture seule de l'état OVH/local).
- Prochaines actions iOS:
  1. Créer un projet Xcode minimal (SwiftUI + AVFoundation) pour scanner EAN/UPC et envoyer la valeur scannée à l'API.
  2. Tester sur iPhone perso via "Personal Team" (compte Apple gratuit) sans toucher au serveur.
- Statut: sauvegarde effectuée, app iOS à démarrer.
