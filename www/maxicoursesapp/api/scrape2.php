<?php
// /maxicoursesapp/api/scrape2.php  (v8.6.1 - Carrefour Piloterr→ScraperAPI→Direct, sanitized)
header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }

error_reporting(E_ALL);
ini_set('display_errors','1');

if (isset($_GET['__ping'])) {
  require_once __DIR__ . '/config.php';
  echo json_encode(['ok'=>true,'vendor'=>(defined('PROXY_VENDOR')?PROXY_VENDOR:''),'ver'=>'v8.6.1'], JSON_UNESCAPED_UNICODE);
  exit;
}

require_once __DIR__ . '/config.php';
function fail($m,$c=400,$extra=null){
  http_response_code($c);
  $out=['ok'=>false,'error'=>$m];
  if (is_array($extra)) { $out = array_merge($out,$extra); }
  echo json_encode($out, JSON_UNESCAPED_UNICODE);
  exit;
}

$url = trim((string)($_POST['url'] ?? $_GET['url'] ?? ''));
if ($url==='') fail('missing url');
$u = parse_url($url); if(!$u || empty($u['scheme']) || empty($u['host'])) fail('bad url');
$host = strtolower($u['host']);
$origin = $u['scheme'].'://'.$u['host'].'/';
$storeRoot = $origin;
if (isset($u['path']) && preg_match('#^/magasin-[^/]+/#',$u['path'],$mm)){ $storeRoot = $u['scheme'].'://'.$u['host'].$mm[0]; }

$trace = isset($_GET['__trace']);
$attempts = [];

$allowed = ['monoprix.fr','carrefour.fr','auchan.fr','intermarche.com','leclercdrive.fr','e.leclerc','courses.leclerc'];
$ok=false; foreach($allowed as $d){ if($host===$d || (strlen($host)>strlen($d) && substr($host,-strlen($d))===$d)) {$ok=true;break;} }
if(!$ok) fail('host not allowed: '.$host,422);

// ---------- Cache ----------
$cacheDir = __DIR__ . '/cache';
if (!is_dir($cacheDir)) @mkdir($cacheDir, 0755, true);
$ttl = defined('CACHE_TTL') ? (int)CACHE_TTL : 3600;
$key = sha1('v8.6.1|'.$url.'|'.(defined('PROXY_VENDOR')?PROXY_VENDOR:'')."|".(defined('PROXY2_VENDOR')?PROXY2_VENDOR:''));
$cacheFile = $cacheDir . '/p_' . $key . '.json';
if ($ttl > 0 && is_file($cacheFile) && (time() - filemtime($cacheFile) < $ttl)) { echo file_get_contents($cacheFile); exit; }

// ---------- Helpers extraction ----------
function norm_price($s){ $s=preg_replace('/[^\d,\.]/','',$s); if(substr_count($s,'.')>1)$s=preg_replace('/\.(?=.*\.)/','',$s); $s=str_replace(',', '.', $s); return (float)$s; }
function extract_jsonld($html){
  if(preg_match_all('#<script[^>]+type=[\"\']application/ld\+json[\"\'][^>]*>(.*?)</script>#si',$html,$m)){
    foreach($m[1] as $blk){ $txt=html_entity_decode(trim($blk)); $cand=json_decode($txt,true);
      if(!is_array($cand)){ $txt=preg_replace('/,\s*}/','}',$txt); $txt=preg_replace('/,\s*]/',']',$txt); $cand=json_decode($txt,true);} 
      if(is_array($cand)){
        $stack=[$cand];
        while($stack){
          $cur=array_pop($stack); if(!is_array($cur)) continue;
          $types=isset($cur['@type'])?(is_array($cur['@type'])?$cur['@type']:[$cur['@type']]):[];
          if(in_array('Product',$types)){
            $name=$cur['name']??null; $off=$cur['offers']??null;
            if($off){
              if(isset($off['price'])) return [$name,norm_price((string)$off['price'])];
              if(is_array($off)&&isset($off[0]['price'])) return [$name,norm_price((string)$off[0]['price'])];
              if(isset($off['priceSpecification']['price'])) return [$name,norm_price((string)$off['priceSpecification']['price'])];
            }
          }
          foreach($cur as $v) if(is_array($v)) $stack[]=$v;
        }
      }
    }
  }
  return [null,null];
}
function find_price_key($o){ $keys=['price','sellingPrice','salePrice','priceValue','amount','value','price_amount','priceInCents','sellingPriceInCents','unitPrice']; if(is_array($o)){ $assoc=array_keys($o)!==range(0,count($o)-1); if(!$assoc){ foreach($o as $v){ $p=find_price_key($v); if($p!==null) return $p; } } else { foreach($o as $k=>$v){ $lk=strtolower((string)$k); if(in_array($lk,array_map('strtolower',$keys))){ if(is_numeric($v)){ $p=(float)$v; if($p>1000)$p=$p/100; if($p>0&&$p<1000) return $p; } if(is_string($v)&&preg_match('/\d+[.,]\d{2}/',$v,$m)) return norm_price($m[0]); } $p=find_price_key($v); if($p!==null) return $p; } } } return null; }
function find_title_key($o){ $keys=['name','title','label']; if(is_array($o)){ $assoc=array_keys($o)!==range(0,count($o)-1); if(!$assoc){ foreach($o as $v){ $t=find_title_key($v); if($t!==null) return $t; } } else { foreach($o as $k=>$v){ $lk=strtolower((string)$k); if(in_array($lk,array_map('strtolower',$keys))&&is_string($v)&&strlen($v)>2) return trim($v); $t=find_title_key($v); if($t!==null) return $t; } } } return null; }
function extract_nextdata($html){ if(preg_match('#<script[^>]+id=[\"\']__NEXT_DATA__[\"\'][^>]*>(.*?)</script>#si',$html,$m)){ $json=html_entity_decode($m[1]); $obj=json_decode($json,true); if(is_array($obj)){ $p=find_price_key($obj); $t=find_title_key($obj); if($p!==null) return [$t,$p]; } } return [null,null]; }
function extract_meta_title($html){ if(preg_match('#property=[\"\']og:title[\"\'][^>]+content=[\"\'](.*?)[\"\']#si',$html,$mm)) return html_entity_decode($mm[1]); if(preg_match('#<title>(.*?)</title>#si',$html,$mm)) return trim(html_entity_decode($mm[1])); return null; }
function extract_text_price($html){
  foreach([
    '#(?<!\d)(\d{1,3}(?:[ .,]\d{3})*(?:[.,]\d{2}))(?!\d)\s*(?:\x{20AC})#u',
    '#(?:\x{20AC})\s*(\d+[.,]\d{2})#u',
    '#\\"price\\"\s*:\s*\\"?(\d+[.,]\d{2})\\"?#i'
  ] as $re){ if(preg_match($re,$html,$m)) return norm_price($m[1]??$m[0]); }
  return null;
}

// ---------- HTTP direct ----------
function http_get_direct($url, $referer){
  $ua='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36';
  $hdrs=[
    'upgrade-insecure-requests: 1',
    'accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'accept-language: fr-FR,fr;q=0.9,en;q=0.8',
    'cache-control: no-cache',
    'pragma: no-cache',
    'sec-ch-ua: "Chromium";v="124", "Google Chrome";v="124", ";Not A Brand";v="99"',
    'sec-ch-ua-mobile: ?0',
    'sec-ch-ua-platform: "Windows"',
    'accept-encoding: gzip, deflate, br',
    'origin: '.$referer,
  ];
  $ch=curl_init($url);
  curl_setopt_array($ch,[
    CURLOPT_RETURNTRANSFER=>true,
    CURLOPT_FOLLOWLOCATION=>true,
    CURLOPT_TIMEOUT=>70,
    CURLOPT_ENCODING=>'',
    CURLOPT_USERAGENT=>$ua,
    CURLOPT_REFERER=>$referer,
    CURLOPT_HTTPHEADER=>$hdrs
  ]);
  $html=curl_exec($ch); $err=curl_error($ch); $code=curl_getinfo($ch,CURLINFO_HTTP_CODE); curl_close($ch);
  return [$html,$code,$err];
}

function http_get_direct_with_cookies($warmUrl, $targetUrl, $referer){
  $ua='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36';
  $hdrs=[
    'upgrade-insecure-requests: 1',
    'accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'accept-language: fr-FR,fr;q=0.9,en;q=0.8',
    'cache-control: no-cache',
    'pragma: no-cache',
    'sec-ch-ua: "Chromium";v="124", "Google Chrome";v="124", ";Not A Brand";v="99"',
    'sec-ch-ua-mobile: ?0',
    'sec-ch-ua-platform: "Windows"',
    'accept-encoding: gzip, deflate, br',
    'origin: '.$referer,
  ];
  $cookie = sys_get_temp_dir().'/mx_cookie_'.sha1($warmUrl.$targetUrl).'.txt';
  // Warmup
  $ch=curl_init($warmUrl);
  curl_setopt_array($ch,[
    CURLOPT_RETURNTRANSFER=>true,
    CURLOPT_FOLLOWLOCATION=>true,
    CURLOPT_TIMEOUT=>70,
    CURLOPT_ENCODING=>'',
    CURLOPT_USERAGENT=>$ua,
    CURLOPT_REFERER=>$referer,
    CURLOPT_HTTPHEADER=>$hdrs,
    CURLOPT_COOKIEJAR=>$cookie,
    CURLOPT_COOKIEFILE=>$cookie
  ]);
  curl_exec($ch); curl_close($ch);
  // Target
  $ch2=curl_init($targetUrl);
  curl_setopt_array($ch2,[
    CURLOPT_RETURNTRANSFER=>true,
    CURLOPT_FOLLOWLOCATION=>true,
    CURLOPT_TIMEOUT=>70,
    CURLOPT_ENCODING=>'',
    CURLOPT_USERAGENT=>$ua,
    CURLOPT_REFERER=>$referer,
    CURLOPT_HTTPHEADER=>$hdrs,
    CURLOPT_COOKIEJAR=>$cookie,
    CURLOPT_COOKIEFILE=>$cookie
  ]);
  $html=curl_exec($ch2); $err=curl_error($ch2); $code=curl_getinfo($ch2,CURLINFO_HTTP_CODE); curl_close($ch2);
  return [$html,$code,$err];
}

// ---------- Piloterr browser ----------
function piloterr_browser_html($apiKey, $url, $referer='https://www.google.com/', $sessionId=null){
  $payload=[
    'url'=>$url,
    'browser'=>true,
    'residential'=>true,
    'session'=>true,
    'session_id'=>($sessionId ? (string)$sessionId : ('maxi-'.substr(md5($url),0,8))),
    'country'=>'fr',
    'headers'=>[
      'Accept'=>'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
      'Accept-Language'=>'fr-FR,fr;q=0.9,en;q=0.8',
      'Upgrade-Insecure-Requests'=>'1',
      'Origin'=>$referer,
      'Referer'=>$referer,
      'sec-ch-ua'=>'"Chromium";v="124", "Google Chrome";v="124", ";Not A Brand";v="99"',
      'sec-ch-ua-mobile'=>'?0',
      'sec-ch-ua-platform'=>'"Windows"',
      'User-Agent'=>'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36',
      'Sec-Fetch-Site'=>'same-origin',
      'Sec-Fetch-Mode'=>'navigate',
      'Sec-Fetch-User'=>'?1',
      'Sec-Fetch-Dest'=>'document',
      'Accept-Encoding'=>'gzip, deflate, br'
    ]
  ];
  $ch=curl_init('https://piloterr.com/api/v2/general/browser');
  curl_setopt_array($ch,[
    CURLOPT_RETURNTRANSFER=>true,
    CURLOPT_TIMEOUT=>70,
    CURLOPT_POST=>true,
    CURLOPT_POSTFIELDS=>json_encode($payload,JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES),
    CURLOPT_HTTPHEADER=>['Content-Type: application/json','x-api-key: '.$apiKey]
  ]);
  $resp=curl_exec($ch); $code=curl_getinfo($ch,CURLINFO_HTTP_CODE); curl_close($ch);
  if($code>=400||$resp===false) return [null,$code];
  $obj=json_decode($resp,true);
  $html=$obj['html']??$obj['content']??null;
  if(!$html) return [null,502];
  return [$html,200];
}

// ---------- ScraperAPI browser ----------
function scraperapi_browser_html($apiKey, $url){
  $qs=http_build_query([
    'api_key'=>$apiKey,
    'url'=>$url,
    'render'=>'true',
    'country_code'=>'fr',
    'device_type'=>'desktop',
    'premium'=>'true',
    'keep_headers'=>'true',
    'session_number'=>'1'
  ]);
  $endpoint='https://api.scraperapi.com/?'.$qs;
  $ch=curl_init($endpoint);
  curl_setopt_array($ch,[CURLOPT_RETURNTRANSFER=>true,CURLOPT_TIMEOUT=>70]);
  $resp=curl_exec($ch); $code=curl_getinfo($ch,CURLINFO_HTTP_CODE); curl_close($ch);
  if($code>=400||$resp===false) return [null,$code];
  return [$resp,200];
}

// ---------- Stratégie par domaine ----------
$html=null; $code=0;
if (strpos($host,'carrefour.fr') !== false) {
  // Carrefour: ScraperAPI → Piloterr (Carrefour referer) → Direct (Carrefour referer)
  if (defined('PROXY2_VENDOR') && PROXY2_VENDOR==='scraperapi' && defined('PROXY2_KEY') && PROXY2_KEY){
    list($html,$code) = scraperapi_browser_html(PROXY2_KEY, $url);
    if($trace) $attempts[]=['via'=>'scraperapi','code'=>$code];
  }
  if((!$html || $code>=400) && defined('PROXY_VENDOR') && PROXY_VENDOR==='piloterr' && defined('PROXY_KEY') && PROXY_KEY) {
    list($html,$code) = piloterr_browser_html(PROXY_KEY, $url, 'https://www.carrefour.fr/');
    if($trace) $attempts[]=['via'=>'piloterr','code'=>$code];
  }
  if((!$html || $code>=400)){
    list($html,$code,$err)=http_get_direct($url,'https://www.carrefour.fr/');
    if($trace) $attempts[]=['via'=>'direct','code'=>$code];
  }
  if((!$html || $code>=400)) fail('fetch error',502, $trace?['trace'=>$attempts]:null);
} else if (strpos($host,'leclercdrive.fr') !== false) {
  $sess = 'leclerc-'.str_replace('.', '-', $host);
  // Warmup on store root to get anti-bot + cookies in same session
  if (defined('PROXY_VENDOR') && PROXY_VENDOR==='piloterr' && defined('PROXY_KEY') && PROXY_KEY) {
    list($warmHtml,$warmCode) = piloterr_browser_html(PROXY_KEY, $storeRoot, $storeRoot, $sess);
    if($trace) $attempts[]=['via'=>'piloterr-warmup','code'=>$warmCode??0,'url'=>$storeRoot];
  }
  // Leclerc Drive: Piloterr (referer Leclerc) → ScraperAPI → Direct (referer Leclerc)
  if (defined('PROXY_VENDOR') && PROXY_VENDOR==='piloterr' && defined('PROXY_KEY') && PROXY_KEY) {
    list($html,$code) = piloterr_browser_html(PROXY_KEY, $url, $storeRoot, $sess);
    if($trace) $attempts[]=['via'=>'piloterr','code'=>$code];
  }
  if((!$html || $code>=400) && defined('PROXY2_VENDOR') && PROXY2_VENDOR==='scraperapi' && defined('PROXY2_KEY') && PROXY2_KEY){
    list($html,$code) = scraperapi_browser_html(PROXY2_KEY, $url);
    if($trace) $attempts[]=['via'=>'scraperapi','code'=>$code];
  }
  if((!$html || $code>=400)){
    list($html,$code,$err)=http_get_direct_with_cookies($storeRoot, $url, $storeRoot);
    if($trace) $attempts[]=['via'=>'direct-cookie','code'=>$code];
  }
  if((!$html || $code>=400)) fail('fetch error',502, $trace?['trace'=>$attempts]:null);
} else if (strpos($host,'monoprix.fr') !== false) {
  list($html,$code,$err) = http_get_direct($url, $origin);
  if($trace) $attempts[]=['via'=>'direct','code'=>$code];
  if(!$html || $code>=400){ if (defined('PROXY_VENDOR') && PROXY_VENDOR==='piloterr' && defined('PROXY_KEY') && PROXY_KEY){ list($html,$code)=piloterr_browser_html(PROXY_KEY,$url); if($trace) $attempts[]=['via'=>'piloterr','code'=>$code]; } }
  if((!$html || $code>=400)) fail('fetch error',502, $trace?['trace'=>$attempts]:null);
} else {
  if (defined('PROXY_VENDOR') && PROXY_VENDOR==='piloterr' && defined('PROXY_KEY') && PROXY_KEY){ list($html,$code)=piloterr_browser_html(PROXY_KEY,$url); if($trace) $attempts[]=['via'=>'piloterr','code'=>$code]; }
  if((!$html || $code>=400)) fail('fetch error',502, $trace?['trace'=>$attempts]:null);
}

// ---- Extraction ----
list($title,$price) = extract_jsonld($html);
if($price===null){ list($t2,$p2)=extract_nextdata($html); if($p2!==null){ $title=$title?:$t2; $price=$p2; } }
if($price===null){ $p3=extract_text_price($html); if($p3!==null) $price=$p3; }
if($title===null) $title = extract_meta_title($html);
if($price===null) fail('price not found',422);

$out = json_encode(['ok'=>true,'host'=>$host,'url'=>$url,'title'=>$title?:'','price'=>$price,'currency'=>'EUR'], JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES);
if ($ttl > 0) @file_put_contents($cacheFile, $out);
echo $out;