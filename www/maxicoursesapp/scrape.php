<?php
header('Content-Type: application/json; charset=utf-8');

function fail($msg, $code=400){ http_response_code($code); echo json_encode(['ok'=>false,'error'=>$msg]); exit; }

$url = isset($_GET['url']) ? trim($_GET['url']) : '';
if ($url==='') fail('missing url');
$u = parse_url($url);
if (!$u || !isset($u['host'])) fail('bad url');
$host = strtolower($u['host']);

// whitelist domaines
$allowed = ['carrefour.fr','www.carrefour.fr','monoprix.fr','www.monoprix.fr'];
if (!in_array($host, $allowed)) fail('host not allowed: '.$host, 422);

// fetch
$ch = curl_init($url);
curl_setopt_array($ch, [
  CURLOPT_RETURNTRANSFER => true,
  CURLOPT_FOLLOWLOCATION => true,
  CURLOPT_TIMEOUT => 20,
  CURLOPT_ENCODING => '',
  CURLOPT_USERAGENT => 'Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36'
]);
$html = curl_exec($ch);
$err = curl_error($ch);
$code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);
if ($html===false || $code>=400) fail('fetch error: '.$err.' code='.$code, 502);

// helper parse JSON-LD
function extract_price_from_jsonld($html){
  if (!preg_match_all('#<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>#si', $html, $m)) return null;
  foreach ($m[1] as $block){
    $block = trim($block);
    // parfois plusieurs JSON concaténés → tenter à la volée
    $candidates = [];
    $decoded = json_decode($block, true);
    if (is_array($decoded)) $candidates[] = $decoded;
    // @graph éventuel
    foreach ($candidates as $cand){
      $stack = [$cand];
      while ($stack){
        $cur = array_pop($stack);
        if (is_array($cur)){
          if (isset($cur['@type'])) {
            $types = is_array($cur['@type']) ? $cur['@type'] : [$cur['@type']];
            if (in_array('Product', $types)){
              $name = $cur['name'] ?? null;
              $offers = $cur['offers'] ?? null;
              if ($offers){
                if (isset($offers['price'])) {
                  $price = $offers['price'];
                  $currency = $offers['priceCurrency'] ?? 'EUR';
                  return [$name, $price, $currency];
                }
                if (is_array($offers) && isset($offers[0]['price'])){
                  $price = $offers[0]['price'];
                  $currency = $offers[0]['priceCurrency'] ?? 'EUR';
                  return [$name, $price, $currency];
                }
              }
            }
          }
          foreach ($cur as $v){ if (is_array($v)) $stack[] = $v; }
        }
      }
    }
  }
  return null;
}

list($name,$price,$currency) = extract_price_from_jsonld($html) ?? [null,null,null];

// fallback meta itemprop/og
if ($price===null){
  if (preg_match('#itemprop=["\']price["\'][^>]+content=["\']([\d\.,]+)["\']#i', $html, $m)) $price = $m[1];
}
if ($name===null){
  if (preg_match('#<title>(.*?)</title>#si', $html, $mm)) $name = trim(html_entity_decode($mm[1]));
}
if ($price===null) fail('price not found', 422);

// normaliser
$price = str_replace([' ', '€'], '', $price);
$price = str_replace(',', '.', $price);
$price = floatval($price);

echo json_encode([
  'ok'=>true,
  'host'=>$host,
  'url'=>$url,
  'title'=>$name,
  'price'=>$price,
  'currency'=>$currency ?: 'EUR'
], JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES);
