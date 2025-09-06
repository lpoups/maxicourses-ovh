<?php
// /www/maxicoursesapp/api/scrape.php
header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');

function fail($msg, $code=400){
  http_response_code($code);
  echo json_encode(['ok'=>false,'error'=>$msg], JSON_UNESCAPED_UNICODE);
  exit;
}

// 1) Paramètres et contrôle domaine
$url = isset($_GET['url']) ? trim($_GET['url']) : '';
if ($url==='') fail('missing url');

$u = parse_url($url);
if (!$u || !isset($u['host'])) fail('bad url');
$host = strtolower($u['host']);

$allowed = [
  'carrefour.fr','www.carrefour.fr','courses.carrefour.fr',
  'monoprix.fr','www.monoprix.fr','courses.monoprix.fr'
];
if (!in_array($host, $allowed)) fail('host not allowed: '.$host, 422);

// 2) Récupération HTML
$ch = curl_init($url);
curl_setopt_array($ch, [
  CURLOPT_RETURNTRANSFER => true,
  CURLOPT_FOLLOWLOCATION => true,
  CURLOPT_TIMEOUT => 20,
  CURLOPT_ENCODING => '',
  CURLOPT_USERAGENT => 'Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36',
  CURLOPT_HTTPHEADER => [
    'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language: fr-FR,fr;q=0.9,en;q=0.8',
    'Cache-Control: no-cache'
  ],
]);
$html = curl_exec($ch);
$err  = curl_error($ch);
$code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);
if ($html===false || $code>=400) fail('fetch error: '.$err.' code='.$code, 502);

// 3) Extraction JSON-LD Product → offers.price
function extract_from_jsonld($html){
  if (!preg_match_all('#<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>#si', $html, $m)) return [null,null,null];
  foreach ($m[1] as $block){
    $block = trim($block);
    $decoded = json_decode($block, true);
    if (!is_array($decoded)) continue;

    // Mettre tout dans une pile pour balayer @graph, arrays, etc.
    $stack = [$decoded];
    while ($stack){
      $cur = array_pop($stack);
      if (!is_array($cur)) continue;

      // Si c'est un Product
      $types = [];
      if (isset($cur['@type'])) $types = is_array($cur['@type']) ? $cur['@type'] : [$cur['@type']];
      if (in_array('Product', $types)){
        $name = $cur['name'] ?? null;
        $offers = $cur['offers'] ?? null;
        if ($offers){
          // cas objet simple
          if (isset($offers['price'])){
            $price = $offers['price'];
            $currency = $offers['priceCurrency'] ?? 'EUR';
            return [$name, $price, $currency];
          }
          // cas tableau d'offres
          if (is_array($offers) && isset($offers[0]['price'])){
            $price = $offers[0]['price'];
            $currency = $offers[0]['priceCurrency'] ?? 'EUR';
            return [$name, $price, $currency];
          }
        }
      }
      // Continuer à descendre
      foreach ($cur as $v){ if (is_array($v)) $stack[] = $v; }
    }
  }
  return [null,null,null];
}

list($name,$price,$currency) = extract_from_jsonld($html);

// 4) Fallbacks génériques (meta, data-*, JSON brut, texte avec symbole €)
if ($price===null && preg_match('#itemprop=["\']price["\'][^>]+content=["\']([\d\.,]+)["\']#i', $html, $m)) $price = $m[1];
if ($price===null && preg_match('#property=["\']product:price:amount["\'][^>]+content=["\']([\d\.,]+)["\']#i', $html, $m)) $price = $m[1];
if ($price===null && preg_match('#data-price=["\']([\d\.,]+)["\']#i', $html, $m)) $price = $m[1];
if ($price===null && preg_match('#"price"\s*:\s*"?([\d\.,]+)"?#i', $html, $m)) $price = $m[1];
if ($price===null && preg_match('#class=["\'][^"\']*price[^"\']*["\'][^>]*>(?:[^0-9]|<)*([\d\.,]+)\s*€#i', $html, $m)) $price = $m[1];

// Titre si absent
if ($name===null){
  if (preg_match('#property=["\']og:title["\'][^>]+content=["\'](.*?)["\']#si', $html, $mm)) $name = html_entity_decode($mm[1]);
  elseif (preg_match('#<title>(.*?)</title>#si', $html, $mm)) $name = trim(html_entity_decode($mm[1]));
}

// 5) Normalisation et sortie
if ($price===null) fail('price not found', 422);

$price = str_replace([' ', '€'], '', $price);
$price = str_replace(',', '.', $price);
$price = (float)$price;
if (!$currency) $currency = 'EUR';

echo json_encode([
  'ok'       => true,
  'host'     => $host,
  'url'      => $url,
  'title'    => $name,
  'price'    => $price,
  'currency' => $currency
], JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES);
