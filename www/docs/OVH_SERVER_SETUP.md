# Déploiement Maxicourses sur le serveur OVH

Objectif : exécuter **toutes** les collectes (Chrome 9222, Playwright, pipeline IA) directement sur OVH sans dépendre d’un navigateur local, tout en conservant l’environnement démo intact.

## Accès (2025-11-19)
- **SSH VPS (collecte Playwright)**  
  - Hôte : `vps-a4a36a41.vps.ovh.net` (IPv4 `91.134.133.156`)  
  - Utilisateur : `ubuntu`  
  - Mot de passe : `PxuJkPxe8jEn!2025` (à changer dès que possible, mais nécessaire pour reprendre la mission).  
  - Repo cloné : `/home/ubuntu/maxicourses-prod` (venv dans `~/maxicourses-prod/.venv`).  
- **FTP mutualisé (publication index2)**  
  - Hôte : `ftp.cluster021.hosting.ovh.net`  
  - Utilisateur : `maxicot`  
  - Mot de passe : `Rantanplan1`  
  - Répertoire cible : `/www/maxicourses-prod/…` (contient `maxicourses_test/results/summary.json` et les sous-dossiers `test-<EAN>` lus par `index2.html`).  
  - Commande type :  
    ```bash
    curl -sS --ftp-create-dirs --user "maxicot:Rantanplan1" \
      -T maxicourses_test/results/summary.json \
      ftp://ftp.cluster021.hosting.ovh.net/www/maxicourses-prod/maxicourses_test/results/summary.json
    ```
  - Toujours pousser `summary.json` + les `latest.json/summary.json` spécifiques de chaque EAN après un run.

## 1. Préparer l’environnement
1. Se connecter en SSH au serveur (ex. `ssh maxi@ovh-server`).
2. Installer les dépendances système :
   ```bash
   sudo apt update
   sudo apt install -y wget curl unzip xvfb fonts-liberation ca-certificates \
       python3 python3-venv python3-pip gnupg
   wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo gpg --dearmor -o /usr/share/keyrings/chrome.gpg
   echo "deb [arch=amd64 signed-by=/usr/share/keyrings/chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
     | sudo tee /etc/apt/sources.list.d/google-chrome.list
   sudo apt update && sudo apt install -y google-chrome-stable
   ```
3. Cloner un **nouvel** exemplaire du dépôt (ne jamais rsync la copie locale) :
   ```bash
   mkdir -p ~/Sites && cd ~/Sites
   git clone git@github.com:maxicourses/price-collector.git maxicourses-ovh
   cd maxicourses-ovh/www
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r maxicourses_test/requirements.txt
   python3 -m playwright install chromium
   ```
4. Exporter les clés/API dans `~/.config/maxicourses/env` (non versionné) puis les sourcer avant chaque run (`source ~/.config/maxicourses/env`).

## 2. Lancer Chrome 9222 côté serveur
1. Utiliser le script dédié headless :
   ```bash
   cd ~/Sites/maxicourses-ovh/www/maxicourses_test
   ./start_chrome_debug_headless.sh
   ```
   Il démarre `google-chrome --headless=new` sur `127.0.0.1:9222` et persiste le profil dans `maxicourses_test/.chrome-debug`.
2. Vérifier qu’il écoute :
   ```bash
   curl -s http://127.0.0.1:9222/json/version | jq '.Browser'
   ```
3. En cas de besoin graphique, ouvrir un tunnel SSH (`ssh -L 9222:127.0.0.1:9222 maxi@ovh-server`) puis pointer Chrome DevTools local sur `http://localhost:9222`; aucun navigateur ne tourne sur la machine user.

## 3. Exécuter les collectes sur OVH
1. Activer l’environnement :
   ```bash
   cd ~/Sites/maxicourses-ovh/www
   source .venv/bin/activate
   export USE_CDP=1
   export CDP_URL="http://127.0.0.1:9222"
   ```
2. Lancer un fetch manuel pour valider :
   ```bash
   cd maxicourses_test
   EAN=3124480200433 QUERY="Orangina 1.5 L" \
     STORE_URL="https://fd12-courses.leclercdrive.fr/magasin-173301-173301-bruges.aspx" \
     python3 manual_leclerc_cdp.py
   ```
3. Pour exécuter toute la pipeline :
   ```bash
   cd maxicourses_test
   ./run_pipeline_server.sh 3092718637033 --adapters leclerc,monoprix
   USE_AI_ASSIST=true ./run_ai_pipeline.sh 3092718637033
   ```
   Le script wrapper applique automatiquement `USE_CDP=1` et `CDP_URL=127.0.0.1:9222`.

## 4. Automatiser via systemd
Les fichiers modèles sont dans `infra/ovh/`. Adapter la variable `WorkingDirectory` et l’utilisateur avant copie dans `/etc/systemd/system/`.

Les unités utilisent l’utilisateur `maxi` et le clone `~/Sites/maxicourses-ovh/www` par défaut ; les modifier si besoin avant copie.

### 4.0 Chrome par magasin (toutes enseignes)
```bash
cd ~/maxicourses-prod/maxicourses_test
./start_chrome_fleet.sh
source .cdp-fleet.env
```
Lance 10 Chrome CDP séparés : City 9222, Market 9223, Super 9224, Auchan 9225, Chronodrive 9226, CourseU 9227, G20 9228, Intermarché 9229, Leclerc 9230, Monoprix 9231. Le fichier `.cdp-fleet.env` exporte les `*_CDP_URL` automatiquement consommés par `run_pipeline_server.sh` et `run_pipeline.py`.

### 4.1 Chrome 9222
```bash
sudo cp infra/ovh/chrome-debug@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now chrome-debug@maxi.service
```

### 4.2 Runs pipeline
1. Copier les unités :
   ```bash
   sudo cp infra/ovh/run-pipeline@.service /etc/systemd/system/
   sudo cp infra/ovh/run-pipeline@.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   ```
2. Lancer une collecte ponctuelle (ex. Orangina) :
   ```bash
   sudo systemctl start run-pipeline@3124480200433.service
   ```
3. Planifier un run horaire :
   ```bash
   sudo systemctl enable --now run-pipeline@3124480200433.timer
   ```
Chaque instance appelle `run_pipeline_server.sh <EAN>` dans le clone OVH (aucun impact sur la copie locale).

## 5. Vérifications
- `journalctl -u chrome-debug@maxi.service -f` : Chrome tourne et se relance après crash.
- `journalctl -u run-pipeline@3124480200433.service -f` : logs Playwright.
- `ls maxicourses_test/results/**/latest.json` : résultats mis à jour côté serveur (`pipeline/index2.html` lit `../results/summary.json`).

> Toute modification spécifique OVH doit rester dans ce clone serveur ou la documentation. La copie locale dédiée aux démos n’est pas éditée.
