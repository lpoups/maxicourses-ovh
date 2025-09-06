#!/usr/bin/env bash
set -euo pipefail
mkdir -p assets/logos
echo "Téléchargement des logos officiels (Wikimedia & sources publiques)..."

curl -L "https://commons.wikimedia.org/wiki/Special:FilePath/E.Leclerc%20logo.svg" -o assets/logos/leclerc.svg
curl -L "https://commons.wikimedia.org/wiki/Special:FilePath/Intermarch%C3%A9%20logo%202009%20classic.svg" -o assets/logos/intermarche.svg
curl -L "https://commons.wikimedia.org/wiki/Special:FilePath/Carrefour%20logo%20no%20tag.svg" -o assets/logos/carrefour.svg
curl -L "https://commons.wikimedia.org/wiki/Special:FilePath/Logo%20Auchan%20(2015).svg" -o assets/logos/auchan.svg
curl -L "https://commons.wikimedia.org/wiki/Special:FilePath/Grand%20Frais%20logo.png" -o assets/logos/grand-frais.svg
curl -L "https://commons.wikimedia.org/wiki/Special:FilePath/Lidl-Logo.svg" -o assets/logos/lidl.svg
curl -L "https://commons.wikimedia.org/wiki/Special:FilePath/Action%20Nederland%20Logo%202020.svg" -o assets/logos/action.svg
curl -L "https://commons.wikimedia.org/wiki/Special:FilePath/SPAR_Logo.svg" -o assets/logos/spar.svg
curl -L "https://commons.wikimedia.org/wiki/Special:FilePath/Logo%20of%20Casino%20Supermarch%C3%A9s.svg" -o assets/logos/casino.svg
curl -L "https://commons.wikimedia.org/wiki/Special:FilePath/Monoprix%20logo.svg" -o assets/logos/monoprix.svg
curl -L "https://commons.wikimedia.org/wiki/Special:FilePath/Cora-logo.svg" -o assets/logos/cora.svg
curl -L "https://commons.wikimedia.org/wiki/Special:FilePath/French%20Netto%20logo%202019.svg" -o assets/logos/netto.svg
curl -L "https://commons.wikimedia.org/wiki/Special:FilePath/Logo%20Leader%20Price%20-%202017.svg" -o assets/logos/leader-price.svg
curl -L "https://commons.wikimedia.org/wiki/Special:FilePath/AldiWorldwideLogo.svg" -o assets/logos/aldi.svg
curl -L "https://www.magasins-u.com/etc.clientlibs/ufrfront/clientlibs/clientlib-design-system/resources/assets/images/logoU/logo-u-express.svg" -o assets/logos/u.svg

echo "Terminé. Les fichiers sont dans assets/logos/"
