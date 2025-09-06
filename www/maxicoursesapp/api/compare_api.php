<?php
declare(strict_types=1);

// ===== API JSON stricte =====
while (ob_get_level()) { ob_end_clean(); }

header('Content-Type: application/json; charset=UTF-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');

// --- Hook adaptateur scrapper (optionnel)
$__candidates = [
    __DIR__ . '/scraper_adapter.php',            // .../api/scraper_adapter.php
    dirname(__DIR__) . '/scraper_adapter.php',   // .../scraper_adapter.php
];
foreach ($__candidates as $__adapter) {
    if (is_file($__adapter)) { require_once $__adapter; break; }
}
unset($__candidates, $__adapter);

/** ---------- Worker fetch + parsing helpers ---------- */

/** Minimal HTTP POST JSON helper. Returns [assoc, raw] */
function http_post_json($url, $payload, $timeout = 18) {
    $ch = curl_init($url);
    $body = json_encode($payload, JSON_UNESCAPED_UNICODE);
    curl_setopt_array($ch, [
        CURLOPT_POST => 1,
        CURLOPT_RETURNTRANSFER => 1,
        CURLOPT_HTTPHEADER => [
            'Content-Type: application/json; charset=utf-8',
            'Accept: application/json',
        ],
        CURLOPT_POSTFIELDS => $body,
        CURLOPT_TIMEOUT => $timeout,
    ]);
    $raw = curl_exec($ch);
    $err = curl_error($ch);
    curl_close($ch);
    if ($raw === false || $raw === null) return [null, $err ?: 'curl_error'];
    $assoc = json_decode($raw, true);
    return [$assoc, $raw];
}

/** Call worker /fetch and return ['ok','code','final_url','bot_protection','html'] */
function worker_fetch(string $worker, string $url, ?string $referer = null, int $timeout = 30, array $opts = []): ?array {
    $endpoint = rtrim($worker, '/').'/fetch';
    $attach    = (bool)($opts['attach']    ?? false);
    $autoclick = (bool)($opts['autoclick'] ?? false);
    $nopuzzle  = (bool)($opts['nopuzzle']  ?? true);

    [$res, $raw] = http_post_json($endpoint, [
        'url'       => $url,
        'referer'   => $referer,
        'attach'    => $attach,
        'autoclick' => $autoclick,
        'nopuzzle'  => $nopuzzle,
    ], $timeout);
    if (!is_array($res)) return null;
    return [
        'ok' => (bool)($res['ok'] ?? false),
        'code' => $res['code'] ?? null,
        'final_url' => $res['final_url'] ?? null,
        'bot_protection' => (bool)($res['bot_protection'] ?? false),
        'html' => $res['html'] ?? '',
    ];
}

/** Normalize absolute URL from href (supports relative) */
function absolutize_url($base, $href) {
    if (!$href) return null;
    if (preg_match('~^https?://~i', $href)) return $href;
    if ($href[0] === '/') {
        return rtrim($base, '/') . $href;
    }
    return rtrim($base, '/') . '/' . $href;
}

/** Extract candidate product links from a search HTML page with scoring tokens */
function extract_candidates($store, $html, $base_url, $tokens) {
    $out = [];
    if (!is_string($html) || $html === '') return [];

    // Prefer JSON islands
    if (preg_match_all('~<script[^>]*type=["\\\']application/(?:json|ld\\+json)["\\\'][^>]*>([\\s\\S]*?)</script>~i', $html, $m)) {
        foreach ($m[1] as $blk) {
            $blk2 = preg_replace('~,\\s*([}\\]])~', '$1', trim($blk));
            $j = json_decode($blk2, true);
            if (!is_array($j)) continue;
            $json = json_encode($j);
            if (preg_match_all('~https?://[^"\\s]+~i', $json, $mm)) {
                foreach ($mm[0] as $u) {
                    $is_prod = false;
                    switch ($store) {
                        case 'carrefour':   $is_prod = (bool)preg_match('~/p/[^/?#]+~i', $u); break;
                        case 'intermarche': $is_prod = (bool)preg_match('~/(?:produit|p)/~i', $u); break;
                        case 'auchan':      $is_prod = (bool)preg_match('~/(?:prod|p|produit)/~i', $u) || (bool)preg_match('~/p-\\d+~', $u); break;
                        case 'monoprix':    $is_prod = (bool)preg_match('~/courses/.*/p/\\d+~i', $u); break;
                        default:            $is_prod = (bool)preg_match('~/p/|/produit~i', $u);
                    }
                    if (!$is_prod) continue;
                    $score = 0; $ul = strtolower($u);
                    foreach ($tokens as $tk) if ($tk && strpos($ul, $tk) !== false) $score += 2;
                    $out[$u] = max($out[$u] ?? 0, $score);
                }
            }
        }
    }

    // Fallback: anchors
    if (preg_match_all('~<a\\s+[^>]*href=["\\\']([^"\\\']+)["\\\'][^>]*>([\\s\\S]*?)</a>~i', $html, $m2, PREG_SET_ORDER)) {
        $base = preg_replace('~^(https?://[^/]+).*~', '$1', $base_url);
        foreach ($m2 as $mm) {
            $href = html_entity_decode($mm[1], ENT_QUOTES | ENT_HTML5, 'UTF-8');
            $text = strtolower(strip_tags($mm[2]));
            $u = absolutize_url($base, $href);
            if (!$u) continue;

            $ok = false;
            switch ($store) {
                case 'carrefour':   $ok = (bool)preg_match('~^https?://[^/]*carrefour\\.fr/(?:p/|[^?#]*/p/)~i', $u); break;
                case 'intermarche': $ok = (bool)preg_match('~^https?://[^/]*intermarche\\.com/.+/(?:produit|p)/~i', $u) || (bool)preg_match('~/catalogue/.*(?:produit|p)/~i', $u); break;
                case 'auchan':      $ok = (bool)preg_match('~^https?://[^/]*auchan\\.fr/.+/(?:p-\\d+|produit|p/)~i', $u); break;
                case 'monoprix':    $ok = (bool)preg_match('~^https?://[^/]*monoprix\\.fr/courses/.*/p/\\d+~i', $u); break;
                default:            $ok = (bool)preg_match('~/p/|/produit~i', $u);
            }
            if (!$ok) continue;

            $score = 0; $ul = strtolower($u);
            foreach ($tokens as $tk) {
                if ($tk && (strpos($ul, $tk) !== false || strpos($text, $tk) !== false)) $score += 2;
            }
            $out[$u] = max($out[$u] ?? 0, $score);
        }
    }

    $arr = [];
    foreach ($out as $u => $sc) $arr[] = ['url' => $u, 'score' => $sc];
    usort($arr, function($a, $b) { return $b['score'] <=> $a['score']; });
    return array_slice($arr, 0, 10);
}

// --- HTTP helper pour récupérer le HTML ---
function http_get(string $url): ?array {
    if (!function_exists('curl_init')) return null;

    $parts  = parse_url($url);
    $scheme = $parts['scheme'] ?? 'https';
    $host   = $parts['host']   ?? '';
    $origin = $scheme . '://' . $host;
    // Referer précis (pour Leclerc: /magasin-XXXX/)
    $storeRoot = $origin . '/';
    if (preg_match('#^(https?://[^/]+/magasin-[^/]+/)#i', $url, $m)) {
        $storeRoot = $m[1];
    }

    $commonHeaders = [
        'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language: fr-FR,fr;q=0.9',
        'Cache-Control: no-cache',
        'Pragma: no-cache',
        'Upgrade-Insecure-Requests: 1',
        'sec-ch-ua: "Chromium";v="124", "Not:A-Brand";v="99"',
        'sec-ch-ua-mobile: ?0',
        'sec-ch-ua-platform: "macOS"',
        'sec-fetch-dest: document',
        'sec-fetch-mode: navigate',
        'sec-fetch-site: same-origin',
        'Referer: ' . $storeRoot,
    ];

    // Cookie jar partagé prévol + requête produit
    $jar = tempnam(sys_get_temp_dir(), 'mxck');

    // 1) Prévol vers la racine pour initialiser les cookies (certains sites l'exigent)
    $ch1 = curl_init($storeRoot);
    curl_setopt_array($ch1, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_MAXREDIRS      => 6,
        CURLOPT_TIMEOUT        => 10,
        CURLOPT_CONNECTTIMEOUT => 5,
        CURLOPT_SSL_VERIFYPEER => true,
        CURLOPT_SSL_VERIFYHOST => 2,
        CURLOPT_ENCODING       => '',
        CURLOPT_HTTPHEADER     => $commonHeaders,
        CURLOPT_USERAGENT      => 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
        CURLOPT_COOKIEFILE     => $jar,
        CURLOPT_COOKIEJAR      => $jar,
        CURLOPT_IPRESOLVE      => CURL_IPRESOLVE_V4,
        CURLOPT_HTTP_VERSION   => CURL_HTTP_VERSION_1_1,
        CURLOPT_AUTOREFERER    => true,
    ]);
    @curl_exec($ch1); // ignore le corps
    @curl_close($ch1);

    // 2) Requête produit réelle, réutilise les cookies
    $ch2 = curl_init($url);
    curl_setopt_array($ch2, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_MAXREDIRS      => 6,
        CURLOPT_TIMEOUT        => 14,
        CURLOPT_CONNECTTIMEOUT => 6,
        CURLOPT_SSL_VERIFYPEER => true,
        CURLOPT_SSL_VERIFYHOST => 2,
        CURLOPT_ENCODING       => '',
        CURLOPT_HTTPHEADER     => $commonHeaders,
        CURLOPT_USERAGENT      => 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
        CURLOPT_COOKIEFILE     => $jar,
        CURLOPT_COOKIEJAR      => $jar,
        CURLOPT_IPRESOLVE      => CURL_IPRESOLVE_V4,
        CURLOPT_HTTP_VERSION   => CURL_HTTP_VERSION_1_1,
        CURLOPT_AUTOREFERER    => true,
        CURLOPT_REFERER        => $storeRoot,
    ]);
    $body  = curl_exec($ch2);
    $code  = (int)curl_getinfo($ch2, CURLINFO_RESPONSE_CODE);
    $final = (string)curl_getinfo($ch2, CURLINFO_EFFECTIVE_URL);
    curl_close($ch2);

    @unlink($jar);

    if ($body === false || $code >= 400) return ['body'=>'','code'=>$code,'final_url'=>$final,'bytes'=>0];
    return ['body'=>$body,'code'=>$code,'final_url'=>$final,'bytes'=>strlen($body)];
}

// --- Petit utilitaire ---
function first_not_empty(...$vals): string {
    foreach ($vals as $v) { if (is_string($v) && trim($v) !== '') return trim($v); }
    return '';
}

// --- Extraction HTML générique (JSON-LD + meta price) ---
function html_scrape(string $url, ?string $store = null): array {
    $resp = http_get($url);
    $title = '';
    $price = null;
    $debug = [ 'src'=>null, 'pattern'=>null, 'code'=>null, 'bytes'=>null, 'final_url'=>null ];

    if ($resp !== null) {
        $html = (string)($resp['body'] ?? '');
        $debug['code'] = $resp['code'] ?? null;
        $debug['bytes'] = $resp['bytes'] ?? null;
        $debug['final_url'] = $resp['final_url'] ?? null;

        if ($html !== '') {
            // Bot/protection pages → ne pas tenter d'extraire un prix hasardeux
            $low = strtolower($html);
            if (preg_match('/captcha-delivery|enable javascript|please enable javascript|pardon the interruption|access denied|request unsuccessful|are you a human|distil|akamai|bot detection|cf-chl|cloudflare|unusual traffic|one more step|cdn-cgi\\/challenge/i', $low)) {
                $debug['src'] = 'bot';
                // On continue seulement pour récupérer un éventuel titre, sans fixer de prix
            }
            // <title>
            if (preg_match('/<title[^>]*>(.*?)<\/title>/is', $html, $m)) {
                $title = html_entity_decode(trim($m[1]), ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
            }
            // og:title
            if ($title === '' && preg_match('/<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']/i', $html, $m)) {
                $title = html_entity_decode(trim($m[1]), ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
            }

            // 1) JSON-LD Product → offers.price
            if ($price === null && preg_match_all('/<script[^>]+type=["\']application\/ld\+json["\'][^>]*>(.*?)<\/script>/is', $html, $blocks)) {
                foreach ($blocks[1] as $block) {
                    $json = trim($block);
                    $data = json_decode($json, true);
                    if (!is_array($data)) continue;
                    $candidates = isset($data[0]) ? $data : [$data];
                    foreach ($candidates as $obj) {
                        if (!is_array($obj)) continue;
                        $type = strtolower((string)($obj['@type'] ?? ''));
                        if ($type !== 'product') continue;
                        $title = first_not_empty($obj['name'] ?? '', $title);
                        $offers = $obj['offers'] ?? null;
                        if (is_array($offers)) {
                            $offersList = isset($offers[0]) ? $offers : [$offers];
                            foreach ($offersList as $off) {
                                if (!is_array($off)) continue;
                                $p = $off['price'] ?? null;
                                if ($p !== null) {
                                    $p = is_string($p) ? str_replace(',', '.', $p) : $p;
                                    if (is_numeric($p)) { $price = (float)$p; $debug['src']='jsonld'; $debug['pattern']='offers.price'; break 3; }
                                }
                            }
                        }
                    }
                }
            }

            // 2) Next.js __NEXT_DATA__ (Carrefour et autres)
            if ($price === null && preg_match('/id=["\']__NEXT_DATA__["\'][^>]*>(.*?)<\/script>/is', $html, $m)) {
                $next = trim(html_entity_decode($m[1], ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8'));
                // Chercher différents schémas de prix dans le JSON
                $rxs = [
                    '/\"finalPrice\"\s*:\s*([0-9]+(?:[\.,][0-9]{1,2})?)/i',
                    '/\"currentPrice\"\s*:\s*\{[^}]*\"value\"\s*:\s*([0-9]+(?:[\.,][0-9]{1,2})?)/i',
                    '/\"price\"\s*:\s*\{[^}]*\"value\"\s*:\s*([0-9]+(?:[\.,][0-9]{1,2})?)/i',
                    '/\"priceValue\"\s*:\s*\{[^}]*\"amount\"\s*:\s*([0-9]+(?:[\.,][0-9]{1,2})?)/i',
                    '/\"formattedValue\"\s*:\s*\"([0-9]+(?:,[0-9]{1,2})?)\s*€\"/i',
                    '/\"value\"\s*:\s*([0-9]+(?:[\.,][0-9]{1,2})?)\s*,\s*\"currencyIso\"\s*:\s*\"EUR\"/i',
                ];
                foreach ($rxs as $rx) {
                    if (preg_match($rx, $next, $mm)) {
                        $p = str_replace(',', '.', $mm[1]);
                        if (is_numeric($p)) { $price = (float)$p; $debug['src']='nextjs'; $debug['pattern']=$rx; }
                        break;
                    }
                }
            }

            // 3) Store‑specific patterns
            if ($price === null && $store) {
                $patterns = [];
                switch ($store) {
                    case 'carrefour':
                        $patterns = [
                            '/\"formattedPrice\"\s*:\s*\"([0-9]+(?:,[0-9]{1,2})?)\s*€\"/i',
                            '/\"finalPrice\"\s*:\s*([0-9]+(?:[\.,][0-9]{1,2})?)/i',
                            '/\"currentPrice\"\s*:\s*\{[^}]*\"value\"\s*:\s*([0-9]+(?:[\.,][0-9]{1,2})?)/i',
                            '/\"priceValue\"\s*:\s*\{[^}]*\"amount\"\s*:\s*([0-9]+(?:[\.,][0-9]{1,2})?)/i',
                            '/\"formattedValue\"\s*:\s*\"([0-9]+(?:,[0-9]{1,2})?)\s*€\"/i',
                            '/\"value\"\s*:\s*([0-9]+(?:[\.,][0-9]{1,2})?)\s*,\s*\"currencyIso\"\s*:\s*\"EUR\"/i',
                        ];
                        break;
                    case 'leclerc':
                        $patterns = [
                            '/\bog:price:amount\b[^>]*content=["\']([0-9]+(?:[\.,][0-9]{1,2})?)["\']/i',
                            '/itemprop=["\']price["\'][^>]*content=["\']([0-9]+(?:[\.,][0-9]{1,2})?)["\']/i',
                        ];
                        break;
                    case 'auchan':
                        $patterns = [
                            '/\"sellingPrice\"\s*:\s*([0-9]+(?:[\.,][0-9]{1,2})?)/i',
                            '/\bog:price:amount\b[^>]*content=["\']([0-9]+(?:[\.,][0-9]{1,2})?)["\']/i',
                        ];
                        break;
                    case 'intermarche':
                        $patterns = [
                            '/\"price\"\s*:\s*\{[^}]*\"value\"\s*:\s*([0-9]+(?:[\.,][0-9]{1,2})?)/i',
                            '/itemprop=["\']price["\'][^>]*content=["\']([0-9]+(?:[\.,][0-9]{1,2})?)["\']/i',
                        ];
                        break;
                    case 'monoprix':
                        $patterns = [
                            '/\bog:price:amount\b[^>]*content=["\']([0-9]+(?:[\.,][0-9]{1,2})?)["\']/i',
                            '/\"price\":\s*\"?([0-9]+(?:[\.,][0-9]{1,2})?)/i',
                        ];
                        break;
                }
                foreach ($patterns as $rx) {
                    if (preg_match($rx, $html, $m)) {
                        $p = str_replace(',', '.', $m[1]);
                        if (is_numeric($p)) { $price = (float)$p; $debug['src']='store'; $debug['pattern']=$rx; break; }
                    }
                }
            }

            // 4) Meta génériques
            if ($price === null && preg_match('/<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\']([^"\']+)["\']/i', $html, $m)) {
                $p = str_replace(',', '.', $m[1]); if (is_numeric($p)) { $price = (float)$p; $debug['src']='meta'; $debug['pattern']='product:price:amount'; }
            }
            if ($price === null && preg_match('/<(?:meta|span)[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)["\']/i', $html, $m)) {
                $p = str_replace(',', '.', $m[1]); if (is_numeric($p)) { $price = (float)$p; $debug['src']='meta'; $debug['pattern']='itemprop price'; }
            }

        }
    }

    if ($title === '') {
        $title = basename(parse_url($url, PHP_URL_PATH) ?: '') ?: 'Produit';
    }

    $out = ['title' => $title, 'price' => $price, 'currency' => 'EUR'];
    if (!empty($_GET['debug'])) $out['debug'] = $debug;
    $out['source'] = 'html';
    return $out;
}

/**
 * Extract title only from HTML (fallback to og:title then URL path basename).
 */
function parse_title_only(string $html, string $url): string {
    $title = '';
    if (preg_match('/<title[^>]*>(.*?)<\/title>/is', $html, $m)) {
        $title = html_entity_decode(trim($m[1]), ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
    } elseif (preg_match('/<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']/i', $html, $m)) {
        $title = html_entity_decode(trim($m[1]), ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
    }
    if ($title === '') {
        $title = basename(parse_url($url, PHP_URL_PATH) ?: '') ?: 'Produit';
    }
    return $title;
}

/**
 * Extract price only from HTML, using lightweight patterns (no title/unit).
 */
function parse_price_only(string $html, ?string $store = null): ?float {
    $price = null;

    // Helper: scan visible text for "X,YY €" while excluding unit prices like €/kg, €/L, per dose, etc.
    $scanVisible = function(string $html) : ?float {
        // Remove scripts/styles then strip tags
        $tmp = preg_replace('/<script[\s\S]*?<\/script>/i', ' ', $html);
        $tmp = preg_replace('/<style[\s\S]*?<\/style>/i',  ' ', $tmp);
        $txt = html_entity_decode(strip_tags($tmp), ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
        // normalize NBSP and thin NBSP to simple spaces
        $txt = str_replace(["\xC2\xA0", "\xE2\x80\xAF"], ' ', $txt);
        $txt = preg_replace('/\s+/', ' ', $txt);

        // Cut before common recommendation sections to reduce false positives
        $lowerAll = function_exists('mb_strtolower') ? mb_strtolower($txt, 'UTF-8') : strtolower($txt);
        $cut = strlen($txt);
        foreach (['vous aimerez aussi','produits similaires','ils achètent aussi','vous pourriez aussi aimer'] as $mk) {
            $pos = function_exists('mb_stripos') ? mb_stripos($lowerAll, $mk, 0, 'UTF-8') : stripos($lowerAll, $mk);
            if ($pos !== false && $pos < $cut) $cut = $pos;
        }
        $txt2 = function_exists('mb_substr') ? mb_substr($txt, 0, $cut, 'UTF-8') : substr($txt, 0, $cut);

        if (preg_match_all('/(\d{1,3}[.,]\d{2})\s*€/u', $txt2, $all, PREG_OFFSET_CAPTURE)) {
            $cands = [];
            foreach ($all[1] as $i => $m1) {
                $val   = $m1[0];
                $start = $all[0][$i][1];
                $len   = strlen($all[0][$i][0]);
                $end   = $start + $len;
                $tail  = function_exists('mb_substr') ? mb_substr($txt2, $end, 36, 'UTF-8') : substr($txt2, $end, 36);
                $head  = function_exists('mb_substr') ? mb_substr($txt2, max(0, $start-36), 36, 'UTF-8') : substr($txt2, max(0, $start-36), 36);
                $tail  = str_replace(["\xC2\xA0", "\xE2\x80\xAF"], ' ', $tail);
                $head  = str_replace(["\xC2\xA0", "\xE2\x80\xAF"], ' ', $head);
                $tailL = function_exists('mb_strtolower') ? mb_strtolower($tail, 'UTF-8') : strtolower($tail);
                $headL = function_exists('mb_strtolower') ? mb_strtolower($head, 'UTF-8') : strtolower($head);

                // unit markers in trailing or leading context (€/kg, €/l, per dose, pour 100 g/ml, etc.)
                $unitMarker = '(?:\/\s*(?:l|kg)|\ble\s*(?:kg|l|litre)\b|\bau\s*(?:kg|l|litre)\b|\bpar\s*(?:l|kg|dose|lavage)\b|\bpour\s*100\s*(?:g|ml)\b|\bsoit\b[^€]{0,16}\/\s*(?:kg|l))';
                if (preg_match('/'.$unitMarker.'/u', $tailL) || preg_match('/'.$unitMarker.'/u', $headL)) {
                    continue; // this is a unit price, ignore
                }

                $p = (float)str_replace(',', '.', $val);
                if ($p >= 1.0 && $p < 1000.0) {
                    $cands[] = $p;
                }
            }
            if (!empty($cands)) {
                sort($cands, SORT_NUMERIC);
                return $cands[0]; // take the smallest plausible full-product price
            }
        }

        // Also catch formats like "€ 9,95"
        if (preg_match_all('/€\s*(\d{1,3}[.,][0-9]{2})/u', $txt2, $all2, PREG_OFFSET_CAPTURE)) {
            $cands = $cands ?? [];
            foreach ($all2[1] as $i => $m1) {
                $val   = $m1[0];
                $start = $all2[0][$i][1];
                $len   = strlen($all2[0][$i][0]);
                $end   = $start + $len;
                $tail  = function_exists('mb_substr') ? mb_substr($txt2, $end, 36, 'UTF-8') : substr($txt2, $end, 36);
                $head  = function_exists('mb_substr') ? mb_substr($txt2, max(0, $start-36), 36, 'UTF-8') : substr($txt2, max(0, $start-36), 36);
                $tail  = str_replace(["\xC2\xA0", "\xE2\x80\xAF"], ' ', $tail);
                $head  = str_replace(["\xC2\xA0", "\xE2\x80\xAF"], ' ', $head);
                $tailL = function_exists('mb_strtolower') ? mb_strtolower($tail, 'UTF-8') : strtolower($tail);
                $headL = function_exists('mb_strtolower') ? mb_strtolower($head, 'UTF-8') : strtolower($head);
                $unitMarker = '(?:\/\s*(?:l|kg)|\ble\s*(?:kg|l|litre)\b|\bau\s*(?:kg|l|litre)\b|\bpar\s*(?:l|kg|dose|lavage)\b|\bpour\s*100\s*(?:g|ml)\b|\bsoit\b[^€]{0,16}\/\s*(?:kg|l))';
                if (preg_match('/'.$unitMarker.'/u', $tailL) || preg_match('/'.$unitMarker.'/u', $headL)) continue;
                $p = (float)str_replace(',', '.', $val);
                if ($p >= 1.0 && $p < 1000.0) $cands[] = $p;
            }
            if (!empty($cands)) {
                sort($cands, SORT_NUMERIC);
                return $cands[0];
            }
        }

        // And formats like "9 € 95" (split euros-cents)
        if (preg_match_all('/\b(\d{1,3})\s*€\s*(\d{2})\b/u', $txt2, $all3, PREG_OFFSET_CAPTURE)) {
            $cands = $cands ?? [];
            foreach ($all3[1] as $i => $mInt) {
                $int   = (int)$mInt[0];
                $cent  = (int)$all3[2][$i][0];
                $start = $all3[0][$i][1];
                $len   = strlen($all3[0][$i][0]);
                $end   = $start + $len;
                $tail  = function_exists('mb_substr') ? mb_substr($txt2, $end, 36, 'UTF-8') : substr($txt2, $end, 36);
                $head  = function_exists('mb_substr') ? mb_substr($txt2, max(0, $start-36), 36, 'UTF-8') : substr($txt2, max(0, $start-36), 36);
                $tail  = str_replace(["\xC2\xA0", "\xE2\x80\xAF"], ' ', $tail);
                $head  = str_replace(["\xC2\xA0", "\xE2\x80\xAF"], ' ', $head);
                $tailL = function_exists('mb_strtolower') ? mb_strtolower($tail, 'UTF-8') : strtolower($tail);
                $headL = function_exists('mb_strtolower') ? mb_strtolower($head, 'UTF-8') : strtolower($head);
                $unitMarker = '(?:\/\s*(?:l|kg)|\ble\s*(?:kg|l|litre)\b|\bau\s*(?:kg|l|litre)\b|\bpar\s*(?:l|kg|dose|lavage)\b|\bpour\s*100\s*(?:g|ml)\b|\bsoit\b[^€]{0,16}\/\s*(?:kg|l))';
                if (preg_match('/'.$unitMarker.'/u', $tailL) || preg_match('/'.$unitMarker.'/u', $headL)) continue;
                $p = $int + ($cent / 100.0);
                if ($p >= 1.0 && $p < 1000.0) $cands[] = $p;
            }
            if (!empty($cands)) {
                sort($cands, SORT_NUMERIC);
                return $cands[0];
            }
        }

        return null;
    };

    // 0) Always try visible text first (works when the DOM renders the main price)
    $vp = $scanVisible($html);
    if ($vp !== null) return $vp;

    // 0.b) DOM price containers (scan a wider window to capture split euros/cents)
    // Many sites (incl. Carrefour) split euros and cents into multiple nested spans.
    // Instead of capturing only the first child tag, scan a larger slice after
    // the price container attribute and then extract "9,95" (or "9 . 95") safely.
    $positions = [];

    // Common container attributes that wrap the main price
    if (preg_match_all('/data-testid="[^"]*(?:price|final-price|current-price|cta-price)[^"]*"/i', $html, $m, PREG_OFFSET_CAPTURE)) {
        foreach ($m[0] as $hit) { $positions[] = (int)$hit[1]; }
    }
    if (preg_match_all('/class="[^"]*(?:ds-price|price|prix|product-price|amount|price__amount|product-price__amount)[^"]*"/i', $html, $m2, PREG_OFFSET_CAPTURE)) {
        foreach ($m2[0] as $hit) { $positions[] = (int)$hit[1]; }
    }

    if (!empty($positions)) {
        sort($positions, SORT_NUMERIC);

        foreach ($positions as $pos) {
            // Take a generous window to include nested spans with cents
            $frag = substr($html, $pos, 2500);
            if ($frag === false || $frag === '') continue;

            // Strip tags and normalize text
            $frag = strip_tags($frag);
            $frag = html_entity_decode($frag, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
            // normalize NBSP and thin NBSP to simple spaces, collapse whitespace
            $frag = str_replace(["\xC2\xA0", "\xE2\x80\xAF"], ' ', $frag);
            $frag = preg_replace('/\s+/', ' ', $frag);
            $fragL = function_exists('mb_strtolower') ? mb_strtolower($frag, 'UTF-8') : strtolower($frag);

            // If the fragment obviously carries unit price semantics, skip it
            if (preg_match('/\/\s*(kg|l)\b|\bpar\s*(kg|l|dose|lavage)\b|\bpour\s*100\s*(g|ml)\b|\bsoit\b[^€]{0,16}\/\s*(kg|l)/u', $fragL)) {
                continue;
            }

            // Prefer full "€ X,YY" or "X,YY €"
            if (preg_match('/€\s*(\d{1,3}[.,]\d{2})/u', $frag, $pm)) {
                $val = (float)str_replace(',', '.', $pm[1]);
                if ($val >= 0.1 && $val < 1000) return $val;
            }
            if (preg_match('/\b(\d{1,3}[.,]\d{2})\s*€/u', $frag, $pm2)) {
                $val = (float)str_replace(',', '.', $pm2[1]);
                if ($val >= 0.1 && $val < 1000) return $val;
            }

            // Also catch split euros/cents like "9 € 95" OR "9 , 95" without an explicit €
            if (preg_match('/\b(\d{1,3})\s*(?:€\s*)?[.,]\s*(\d{2})\b/u', $frag, $pm3)) {
                $val = ((int)$pm3[1]) + ((int)$pm3[2]) / 100.0;
                if ($val >= 0.1 && $val < 1000) return $val;
            }
        }
    }

    // JSON‑LD Product → offers.price (prefer the per‑item price; ignore unit price contexts)
    if (preg_match_all('/<script[^>]+type=["\']application\/ld\+json["\'][^>]*>(.*?)<\/script>/is', $html, $blocks)) {
        foreach ($blocks[1] as $block) {
            $json = trim($block);
            // be tolerant to trailing commas
            $json = preg_replace('/,(\s*[}\]])/', '$1', $json);
            $data = json_decode($json, true);
            if (!is_array($data)) continue;
            $arr = isset($data[0]) ? $data : [$data];
            foreach ($arr as $obj) {
                if (!is_array($obj)) continue;
                $type = strtolower((string)($obj['@type'] ?? ''));
                if ($type !== 'product') continue;

                $offers = $obj['offers'] ?? null;
                if (!is_array($offers)) continue;
                $offersList = isset($offers[0]) ? $offers : [$offers];

                foreach ($offersList as $off) {
                    if (!is_array($off)) continue;
                    // Try price first, then priceSpecification.price
                    $p = $off['price'] ?? null;
                    if ($p === null && isset($off['priceSpecification']) && is_array($off['priceSpecification'])) {
                        $p = $off['priceSpecification']['price'] ?? null;
                    }
                    if ($p !== null) {
                        $p = is_string($p) ? str_replace(',', '.', $p) : $p;
                        if (is_numeric($p)) {
                            $val = (float)$p;
                            if ($val >= 0.1 && $val < 1000) {
                                return $val;
                            }
                        }
                    }
                }
            }
        }
    }

    // Helper: pick numeric price from JSON-like blobs but avoid unit/per‑kg contexts near the match.
    $pickFromJson = function(string $blob, array $regexes) : ?float {
        $cands = [];
        foreach ($regexes as $rx) {
            if (!preg_match_all($rx, $blob, $matches, PREG_OFFSET_CAPTURE)) continue;
            foreach ($matches[1] as $m) {
                $raw = $m[0];
                $pos = $m[1];
                // widen context to detect unit/weight mentions around the match
                $ctx = substr($blob, max(0, $pos - 180), 360);
                $ctxL = strtolower($ctx);
                // Skip if context clearly refers to unit prices
                if (preg_match('/perunit|unitprice|priceper|unit_price|unitofmeasure\"?\s*:\s*\"?(?:kilogram|liter)|\/\s*(kg|l)|\bkg\b|\blitre\b|\bliter\b|\bper\s*(kg|l)\b|\b100\s*(g|ml)\b|\bpour\s*100\s*(g|ml)\b/u', $ctxL)) {
                    continue;
                }
                $val = str_replace(',', '.', $raw);
                if (is_numeric($val)) {
                    $num = (float)$val;
                    if ($num >= 0.1 && $num < 1000) $cands[] = $num;
                }
            }
        }
        if (empty($cands)) return null;
        sort($cands, SORT_NUMERIC);
        return $cands[0];
    };

    // A) Next.js island (__NEXT_DATA__) – prefer fields that usually carry per‑item price
    if (preg_match('/id=["\']__NEXT_DATA__["\'][^>]*>(.*?)<\/script>/is', $html, $m)) {
        $next = trim(html_entity_decode($m[1], ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8'));
        $rxs = [
            '/"currentPrice"\s*:\s*\{[^}]*"value"\s*:\s*([0-9]+(?:[.,][0-9]{1,2})?)/i',
            '/"finalPrice"\s*:\s*([0-9]+(?:[.,][0-9]{1,2})?)/i',
            '/"price"\s*:\s*\{[^}]*"value"\s*:\s*([0-9]+(?:[.,][0-9]{1,2})?)/i',
            '/"priceValue"\s*:\s*\{[^}]*"amount"\s*:\s*([0-9]+(?:[.,][0-9]{1,2})?)/i',
            '/"amount"\s*:\s*\{[^}]*"value"\s*:\s*([0-9]+(?:[.,][0-9]{1,2})?)/i',
            '/"formattedValue"\s*:\s*"([0-9]+(?:,[0-9]{1,2})?)(?:\\u00a0|\s)*€"/i',
            '/"priceLabel"\s*:\s*"([0-9]+(?:,[0-9]{1,2})?)(?:\\u00a0|\s)*€"/i',
            '/"label"\s*:\s*"([0-9]+(?:,[0-9]{1,2})?)(?:\\u00a0|\s)*€"/i',
            '/"value"\s*:\s*([0-9]+(?:[.,][0-9]{1,2})?)\s*,\s*"currency(?:Iso|)"\s*:\s*"EUR"/i',
        ];
        $p = $pickFromJson($next, $rxs);
        if ($p !== null) return $p;
    }

    // NEW: decode __NEXT_DATA__ and traverse to find a per-item price (avoid unit prices like €/kg or €/L)
    if (preg_match('/id=["\']__NEXT_DATA__["\'][^>]*>(.*?)<\/script>/is', $html, $mJson)) {
        $raw = html_entity_decode($mJson[1], ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
        $data = json_decode($raw, true);
        if (is_array($data)) {
            $bestVal = null;        // numeric price candidate
            $bestIsUnit = true;     // whether candidate looked like a unit price
            $walk = function($node) use (&$walk, &$bestVal, &$bestIsUnit) {
                if (!is_array($node)) return;

                // Detect unit-of-measure in this subtree
                $ctx  = json_encode($node);
                $ctxL = strtolower($ctx ?: '');
                $uomIsUnit = false;
                if (preg_match('/"unitofmeasure"\s*:\s*"?(kilogram|liter|milliliter|gram)"/i', $ctxL)) $uomIsUnit = true;
                if (preg_match('/"unit"\s*:\s*"?(kilogram|liter|milliliter|gram)"/i', $ctxL)) $uomIsUnit = true;
                if (preg_match('/\/\s*(kg|l)\b/i', $ctxL) || preg_match('/\b(kg|l|litre|liter)\b/i', $ctxL) || preg_match('/\b100\s*(g|ml)\b/i', $ctxL)) $uomIsUnit = true;
                if (preg_match('/"unitofmeasure"\s*:\s*"?(each|piece|unit)"/i', $ctxL)) $uomIsUnit = false;

                // Collect numeric candidates for common keys
                $numAt = function($v) {
                    if (is_string($v)) $v = str_replace(',', '.', $v);
                    return is_numeric($v) ? (float)$v : null;
                };

                $cands = [];
                // structured numeric containers
                foreach (['currentPrice','finalPrice','priceValue','price','amount','salePrice','sellingPrice','offerPrice'] as $k) {
                    if (isset($node[$k]) && is_array($node[$k])) {
                        foreach (['value','amount','valueWithTax'] as $kk) {
                            if (isset($node[$k][$kk])) {
                                $n = $numAt($node[$k][$kk]);
                                if ($n !== null) $cands[] = $n;
                            }
                        }
                    }
                }
                // flat formatted strings like "9,95 €"
                foreach (['formattedValue','priceLabel','label'] as $k) {
                    if (isset($node[$k]) && is_string($node[$k]) && preg_match('/([0-9]+(?:,[0-9]{1,2})?)(?:\\u00a0|\s)*€/i', $node[$k], $mm)) {
                        $n = (float)str_replace(',', '.', $mm[1]);
                        $cands[] = $n;
                    }
                }
                // cents keys on the node itself
                foreach ($node as $k => $v) {
                    if (is_numeric($v) && preg_match('/(inCents|centAmount|amountInCents|priceInCents|sellingPriceInCents|valueInCents)$/i', (string)$k)) {
                        $n = ((float)$v) / 100.0;
                        $cands[] = $n;
                    }
                }

                foreach ($cands as $val) {
                    if ($val >= 0.1 && $val < 1000) {
                        if ($bestVal === null || ($bestIsUnit && !$uomIsUnit) || (!$uomIsUnit && $val < $bestVal) || ($uomIsUnit && $bestIsUnit && $val < $bestVal)) {
                            $bestVal = $val; $bestIsUnit = $uomIsUnit;
                        }
                    }
                }

                // Recurse
                foreach ($node as $v) { if (is_array($v)) $walk($v); }
            };
            $walk($data);
            if ($bestVal !== null && !$bestIsUnit) return $bestVal;
            if ($bestVal !== null) return $bestVal; // fallback to any price if only unit price found
        }
    }

    // Extra fallbacks: aria-label and inline "priceText"
    if (preg_match('/aria-label="[^"]*?(\d{1,3}(?:,[0-9]{1,2})?)\s*€/i', $html, $m)) {
        $num = (float)str_replace(',', '.', $m[1]);
        if ($num >= 0.1 && $num < 1000) return $num;
    }
    if (preg_match('/"priceText"\s*:\s*"(\d{1,3}(?:,[0-9]{1,2})?)\s*€"/i', $html, $m)) {
        $num = (float)str_replace(',', '.', $m[1]);
        if ($num >= 0.1 && $num < 1000) return $num;
    }

    // Carrefour/others explicit cents fields (server data) — prefer full item price expressed in cents
    if (preg_match('/"(?:priceInCents|sellingPriceInCents|valueInCents|amountInCents|centAmount)"\s*:\s*(\d{2,7})/i', $html, $m)) {
        $num = ((int)$m[1]) / 100.0;
        if ($num >= 0.1 && $num < 1000) return $num;
    }

    // Carrefour DOM hint: price inside data-testid (avoid unit prices via $scanVisible filter above)
    if ($store === 'carrefour' && preg_match('/data-testid="[^"]*(?:price|cta-price)[^"]*"[^>]*>[^<]*?(\d{1,3}[.,]\d{2})\s*€/i', $html, $m)) {
        $num = (float)str_replace(',', '.', $m[1]);
        if ($num >= 0.1 && $num < 1000) return $num;
    }

    // B) Store-specific JSON/meta patterns – still apply the context guard
    if ($store) {
        $patterns = [];
        switch ($store) {
            case 'carrefour':
                $patterns = [
                    '/"currentPrice"\s*:\s*\{[^}]*"value"\s*:\s*([0-9]+(?:[.,][0-9]{1,2})?)/i',
                    '/"finalPrice"\s*:\s*([0-9]+(?:[.,][0-9]{1,2})?)/i',
                    '/"priceValue"\s*:\s*\{[^}]*"amount"\s*:\s*([0-9]+(?:[.,][0-9]{1,2})?)/i',
                    '/"price"\s*:\s*\{[^}]*"value"\s*:\s*([0-9]+(?:[.,][0-9]{1,2})?)/i',
                    '/"formattedValue"\s*:\s*"([0-9]+(?:,[0-9]{1,2})?)\s*€"/i',
                    '/"priceLabel"\s*:\s*"([0-9]+(?:,[0-9]{1,2})?)\s*€"/i',
                    '/"label"\s*:\s*"([0-9]+(?:,[0-9]{1,2})?)\s*€"/i',
                ];
                break;
            case 'leclerc':
                $patterns = [
                    '/\bog:price:amount\b[^>]*content=["\']([0-9]+(?:[.,][0-9]{1,2})?)["\']/i',
                    '/itemprop=["\']price["\'][^>]*content=["\']([0-9]+(?:[.,][0-9]{1,2})?)["\']/i',
                ];
                break;
            case 'auchan':
                $patterns = [
                    '/"sellingPrice"\s*:\s*([0-9]+(?:[.,][0-9]{1,2})?)/i',
                    '/\bog:price:amount\b[^>]*content=["\']([0-9]+(?:[.,][0-9]{1,2})?)["\']/i',
                ];
                break;
            case 'intermarche':
                $patterns = [
                    '/"price"\s*:\s*\{[^}]*"value"\s*:\s*([0-9]+(?:[.,][0-9]{1,2})?)/i',
                    '/itemprop=["\']price["\'][^>]*content=["\']([0-9]+(?:[.,][0-9]{1,2})?)["\']/i',
                ];
                break;
            case 'monoprix':
                $patterns = [
                    '/\bog:price:amount\b[^>]*content=["\']([0-9]+(?:[.,][0-9]{1,2})?)["\']/i',
                    '/"price":\s*"?(?:EUR|€)?\s*([0-9]+(?:[.,][0-9]{1,2})?)/i',
                ];
                break;
        }
        if (!empty($patterns)) {
            $p = $pickFromJson($html, $patterns);
            if ($p !== null) return $p;
        }
    }

    // C) Generic meta fallbacks
    if (preg_match('/<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\']([^"\']+)["\']/i', $html, $m)) {
        $p = str_replace(',', '.', $m[1]); if (is_numeric($p)) return (float)$p;
    }
    if (preg_match('/<(?:meta|span)[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)["\']/i', $html, $m)) {
        $p = str_replace(',', '.', $m[1]); if (is_numeric($p)) return (float)$p;
    }

    // D) As a last resort, try visible scan again (some pages lazy-load content)
    $vp2 = $scanVisible($html);
    if ($vp2 !== null) return $vp2;

    return null;
}

/**
 * Lance le scraper Python local (Python 3 requis) et retourne ['title','price','currency','unit'?] ou null.
 * Appelle: <py3> maxicoursesapp/api/scraper.py "<URL>"
 */
function run_py(string $url): ?array {
    $script = __DIR__ . '/scraper.py';
    if (!is_file($script)) return null;

    $disabled = array_map('trim', explode(',', (string)ini_get('disable_functions')));
    $is_disabled = function(string $fn) use ($disabled): bool { return in_array($fn, $disabled, true); };

    // Détection d'un binaire Python 3 fonctionnel
    $candidates = ['/usr/local/bin/python3','/usr/bin/python3','python3','python'];
    $py_bin = null; $ver = null; $rcv = null;
    foreach ($candidates as $bin) {
        $lines = []; $rcv = 0; @exec($bin.' -V 2>&1', $lines, $rcv);
        $outv = trim(implode("\n", $lines));
        if ($rcv === 0 && stripos($outv, 'Python 3') !== false) { $py_bin = $bin; $ver = $outv; break; }
    }
    if ($py_bin === null) {
        if (!empty($_GET['debug'])) {
            return ['title'=>'', 'price'=>null, 'currency'=>'EUR', 'debug'=>['used'=>null, 'error'=>'no_python3', 'candidates'=>$candidates]];
        }
        return null;
    }

    $cmd = $py_bin . ' ' . escapeshellarg($script) . ' ' . escapeshellarg($url);

    // 1) proc_open si dispo (stdout+stderr séparés pour debug)
    if (!$is_disabled('proc_open') && function_exists('proc_open')) {
        $desc = [0=>['pipe','r'], 1=>['pipe','w'], 2=>['pipe','w']];
        $proc = @proc_open($cmd, $desc, $pipes, dirname($script));
        if (is_resource($proc)) {
            fclose($pipes[0]);
            $out = stream_get_contents($pipes[1]); fclose($pipes[1]);
            $err = stream_get_contents($pipes[2]); fclose($pipes[2]);
            $rc  = proc_close($proc);
            if (is_string($out) && $out !== '') {
                $j = json_decode($out, true);
                if (is_array($j) && !empty($j['ok']) && array_key_exists('price', $j)) {
                    $res = [
                        'title'    => (string)($j['title'] ?? ''),
                        'price'    => is_numeric($j['price'] ?? null) ? (float)$j['price'] : null,
                        'currency' => (string)($j['currency'] ?? 'EUR'),
                        'source'   => 'py',
                    ];
                    if (isset($j['unit']) && is_array($j['unit'])) $res['unit'] = $j['unit'];
                    if (!empty($_GET['debug'])) $res['debug'] = ['used'=>'proc_open:'.$py_bin, 'ver'=>$ver, 'rc'=>$rc, 'stderr'=>substr((string)$err,0,2000)];
                    return $res;
                }
            }
            if (!empty($_GET['debug'])) return ['title'=>'', 'price'=>null, 'currency'=>'EUR', 'debug'=>['used'=>'proc_open:'.$py_bin, 'ver'=>$ver, 'rc'=>$rc, 'tail'=>substr((string)$out,0,2000)]];
            return null;
        }
    }

    // 2) exec() avec capture stderr (2>&1) pour debug
    if (!$is_disabled('exec') && function_exists('exec')) {
        $lines = []; $rc = 0; @exec($cmd . ' 2>&1', $lines, $rc);
        $out = implode("\n", $lines);
        if ($out !== '') {
            $j = json_decode($out, true);
            if (is_array($j) && !empty($j['ok']) && array_key_exists('price', $j)) {
                $res = [
                    'title'    => (string)($j['title'] ?? ''),
                    'price'    => is_numeric($j['price'] ?? null) ? (float)$j['price'] : null,
                    'currency' => (string)($j['currency'] ?? 'EUR'),
                    'source'   => 'py',
                ];
                if (isset($j['unit']) && is_array($j['unit'])) $res['unit'] = $j['unit'];
                if (!empty($_GET['debug'])) $res['debug'] = ['used'=>'exec:'.$py_bin, 'ver'=>$ver, 'rc'=>$rc];
                return $res;
            }
        }
        if (!empty($_GET['debug'])) return ['title'=>'', 'price'=>null, 'currency'=>'EUR', 'debug'=>['used'=>'exec:'.$py_bin, 'ver'=>$ver, 'rc'=>$rc, 'tail'=>substr($out,0,2000)]];
        return null;
    }

    // 3) shell_exec en dernier recours
    if (!$is_disabled('shell_exec') && function_exists('shell_exec')) {
        $out = @shell_exec($cmd . ' 2>&1');
        if (is_string($out) && $out !== '') {
            $j = json_decode($out, true);
            if (is_array($j) && !empty($j['ok']) && array_key_exists('price', $j)) {
                $res = [
                    'title'    => (string)($j['title'] ?? ''),
                    'price'    => is_numeric($j['price'] ?? null) ? (float)$j['price'] : null,
                    'currency' => (string)($j['currency'] ?? 'EUR'),
                    'source'   => 'py',
                ];
                if (isset($j['unit']) && is_array($j['unit'])) $res['unit'] = $j['unit'];
                if (!empty($_GET['debug'])) $res['debug'] = ['used'=>'shell_exec:'.$py_bin, 'ver'=>$ver];
                return $res;
            }
        }
        if (!empty($_GET['debug'])) return ['title'=>'', 'price'=>null, 'currency'=>'EUR', 'debug'=>['used'=>'shell_exec:'.$py_bin, 'ver'=>$ver, 'tail'=>substr((string)$out,0,2000)]];
        return null;
    }

    if (!empty($_GET['debug'])) return ['title'=>'', 'price'=>null, 'currency'=>'EUR', 'debug'=>['used'=>null, 'error'=>'no_exec_capability', 'ver'=>$ver]];
    return null;
}

/**
 * Appelle un worker HTTP externe qui renvoie {ok,title,price,currency,unit?}
 * SCRAPER_WORKER peut être soit l'URL racine du worker (on ajoutera /scrape),
 * soit directement l'endpoint /scrape.
 * On accepte aussi ?worker=... pour les tests.
 */
function run_worker(string $url): ?array {
    $base = getenv('SCRAPER_WORKER');
    if (!$base && isset($_GET['worker'])) {
        $base = (string)$_GET['worker'];
    }
    if (!$base) return null;

    $endpoint = rtrim($base, '/');
    if (!preg_match('~/scrape$~i', $endpoint)) {
        $endpoint .= '/scrape';
    }

    if (!function_exists('curl_init')) return null;

    // POST JSON (chemin principal)
    $payload = json_encode(['url' => $url], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    $ch = curl_init($endpoint);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_TIMEOUT        => 20,
        CURLOPT_CONNECTTIMEOUT => 6,
        CURLOPT_SSL_VERIFYPEER => true,
        CURLOPT_SSL_VERIFYHOST => 2,
        CURLOPT_HTTPHEADER     => [
            'Accept: application/json',
            'Content-Type: application/json',
        ],
        CURLOPT_POST           => true,
        CURLOPT_POSTFIELDS     => $payload,
        CURLOPT_USERAGENT      => 'MaxicoursesWorker/1.0',
    ]);
    $body = curl_exec($ch);
    $code = (int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);

    // Fallback GET ?url= si le POST échoue
    if (!is_string($body) || $body === '' || $code >= 400) {
        $q = $endpoint . (strpos($endpoint, '?') === false ? '?' : '&') . 'url=' . rawurlencode($url);
        $ch = curl_init($q);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => true,
            CURLOPT_TIMEOUT        => 12,
            CURLOPT_CONNECTTIMEOUT => 6,
            CURLOPT_SSL_VERIFYPEER => true,
            CURLOPT_SSL_VERIFYHOST => 2,
            CURLOPT_HTTPHEADER     => ['Accept: application/json'],
            CURLOPT_USERAGENT      => 'MaxicoursesWorker/1.0',
        ]);
        $body = curl_exec($ch);
        $code = (int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        curl_close($ch);
        if (!is_string($body) || $body === '' || $code >= 400) return null;
    }

    $j = json_decode($body, true);
    if (!is_array($j) || empty($j['ok'])) return null;

    $res = [
        'title'    => (string)($j['title'] ?? ''),
        'price'    => is_numeric($j['price'] ?? null) ? (float)$j['price'] : null,
        'currency' => (string)($j['currency'] ?? 'EUR'),
        'source'   => 'worker',
    ];
    if (isset($j['unit']) && is_array($j['unit'])) $res['unit'] = $j['unit'];
    return $res;
}

/**
 * Scrape un produit et renvoie :
 *   ['title' => string, 'price' => float|null, 'currency' => 'EUR', 'unit'? => array]
 *
 * Ordre d'essai : Worker HTTP → Python local → Adapter PHP → HTML (JSON-LD/meta) → CLI → Fallback
 */
function scrape(string $url): array {
    // 1) Worker HTTP externe prioritaire (ngrok/local)
    $wk = run_worker($url);
    if (is_array($wk) && array_key_exists('price', $wk)) {
        return $wk;
    }

    // 2) Scraper Python (si disponible localement)
    $py = run_py($url);
    if (is_array($py) && array_key_exists('price', $py) && is_numeric($py['price'])) {
        return $py;
    }

    // 2b) Adapter PHP en fallback (désactivé par défaut; activer avec MAXI_ALLOW_ADAPTER=1)
    if (function_exists('mx_scrape') && getenv('MAXI_ALLOW_ADAPTER') === '1') {
        try {
            $r = mx_scrape($url);
            if (is_array($r) && array_key_exists('price', $r)) {
                return [
                    'title'    => (string)($r['title'] ?? ''),
                    'price'    => is_numeric($r['price']) ? (float)$r['price'] : null,
                    'currency' => (string)($r['currency'] ?? 'EUR'),
                    'source'   => 'adapter',
                ];
            }
        } catch (\Throwable $e) { /* noop */ }
    }

    // 3) HTML direct (JSON-LD/meta)
    $h = html_scrape($url, host_to_store($url));
    if (!empty($h)) return $h;

    // 4) Commande CLI via ENV (optionnelle)
    $tpl = getenv('MAXI_SCRAPER_CMD');
    if ($tpl && getenv('MAXI_ALLOW_CLI') === '1') {
        $cmd = sprintf($tpl, escapeshellarg($url));
        $out = @shell_exec($cmd . ' 2>/dev/null');
        if (is_string($out) && $out !== '') {
            $j = json_decode($out, true);
            if (is_array($j) && array_key_exists('price', $j)) {
                return [
                    'title'    => (string)($j['title'] ?? ''),
                    'price'    => is_numeric($j['price']) ? (float)$j['price'] : null,
                    'currency' => (string)($j['currency'] ?? 'EUR'),
                    'source'   => 'cli',
                ];
            }
        }
    }

    // 5) Fallback minimal
    $title = basename(parse_url($url, PHP_URL_PATH) ?: '') ?: 'Produit';
    return ['title' => $title, 'price' => null, 'currency' => 'EUR'];
}

// ===== Utils =====
function host_to_store(string $url): ?string {
    $h = strtolower(parse_url($url, PHP_URL_HOST) ?? '');
    if ($h === '') return null;
    if (strpos($h, 'leclerc') !== false)      return 'leclerc';
    if (strpos($h, 'carrefour') !== false)    return 'carrefour';
    if (strpos($h, 'intermarche') !== false)  return 'intermarche';
    if (strpos($h, 'auchan') !== false)       return 'auchan';
    if (strpos($h, 'monoprix') !== false)     return 'monoprix';
    return null;
}


/**
 * -------- Equivalent finder helpers --------
 * We start simple: build a site search URL per store, fetch the HTML, extract
 * candidate product links with store‑specific regexes, and (optionally) score
 * them by comparing tokens (brand, form "pods/capsules", dose/weight).
 * This endpoint is read-only and does not alter existing routes.
 */

function norm_tokenize(string $s): array {
    $s = mb_strtolower($s, 'UTF-8');
    // keep letters/numbers/space
    $s = preg_replace('~[^0-9a-zàâäçéèêëîïôöùûüÿñ\s\-]~iu', ' ', $s);
    $s = preg_replace('~\s+~', ' ', trim($s));
    $parts = array_values(array_filter(explode(' ', $s), fn($t) => $t !== ''));
    return $parts;
}

function extract_features_from_title(string $title, array $unit = []): array {
    $toks = norm_tokenize($title);
    $features = [
        'brand' => null,
        'form'  => null,     // pods/capsules/liquide/poudre
        'doses' => $unit['doses'] ?? null,
        'kg'    => $unit['kg'] ?? null,
        'liters'=> $unit['liters'] ?? null,
    ];
    // brand candidates – add more if needed
    foreach (['ariel','skip','persil','omo','dash','lenor','xtra','le chat','mir','carrefour','marque repere'] as $b) {
        $b2 = norm_tokenize($b);
        $ok = true; foreach ($b2 as $tt) { if (!in_array($tt, $toks, true)) { $ok=false; break; } }
        if ($ok) { $features['brand'] = $b2[0]; break; }
    }
    // form
    foreach (['pods','capsules','capsule','tablettes','liquide','poudre','gel'] as $f) {
        if (in_array($f, $toks, true)) { $features['form'] = $f; break; }
    }
    // doses in text e.g. 19, 34, 40
    if ($features['doses'] === null && preg_match('~\b(\d{1,3})\s*(?:caps|capsules|doses|pods)\b~i', $title, $m)) {
        $features['doses'] = (int)$m[1];
    }
    // kg or g
    if ($features['kg'] === null && preg_match('~\b(\d+(?:[.,]\d+)?)\s*(kg|g)\b~i', $title, $m)) {
        $v = (float)str_replace(',', '.', $m[1]);
        $features['kg'] = (strtolower($m[2]) === 'g') ? $v/1000.0 : $v;
    }
    // liters
    if ($features['liters'] === null && preg_match('~\b(\d+(?:[.,]\d+)?)\s*l\b~i', $title, $m)) {
        $features['liters'] = (float)str_replace(',', '.', $m[1]);
    }
    return $features;
}

function build_query_from_features(array $features, string $title): string {
    $tokens = [];
    if (!empty($features['brand'])) $tokens[] = $features['brand'];
    if (!empty($features['form']))  $tokens[] = $features['form']; // pods/capsules/liquide...
    if (!empty($features['doses'])) $tokens[] = (string)$features['doses']; // ex: 19

    // fallback: mot catégorie si pas de "form"
    if (empty($features['form']) && preg_match('~\b(lessive|pods?|capsules?)\b~i', $title, $m)) {
        $tokens[] = $m[1];
    }

    // Évite d'injecter des décimaux (0.346 kg, 1.75 L) qui cassent souvent la recherche côté enseigne
    // Si rien d'exploitable, prends 3-4 tokens forts du titre
    $q = trim(implode(' ', array_unique($tokens)));
    if ($q === '') {
        $tt = norm_tokenize($title);
        $q = implode(' ', array_slice($tt, 0, 4));
    }
    return $q;
}

function store_search_url(string $store, string $query): ?string {
    $q = rawurlencode($query);
    switch ($store) {
        case 'carrefour':    return "https://www.carrefour.fr/s?q={$q}";
        case 'intermarche':  return "https://www.intermarche.com/recherche?terme={$q}";
        case 'auchan':       return "https://www.auchan.fr/recherche?q={$q}";
        case 'monoprix':     return "https://www.monoprix.fr/courses/recherche?q={$q}";
        default: return null;
    }
}

function extract_product_links_for_store(string $store, string $html): array {
    $links = [];
    if (!is_string($html) || $html === '') return [];

    // Base host per store
    $base = [
        'carrefour'   => 'https://www.carrefour.fr',
        'intermarche' => 'https://www.intermarche.com',
        'auchan'      => 'https://www.auchan.fr',
        'monoprix'    => 'https://www.monoprix.fr',
    ][$store] ?? '';

    // Helper: push absolute
    $push = function(string $u) use (&$links, $base) {
        if ($u === '') return;
        // decode JSON-escaped
        $u = str_replace(['\\/', '&amp;'], ['/', '&'], $u);
        if (strpos($u, 'http') !== 0) {
            if ($u[0] !== '/') $u = '/'.$u;
            if ($base) $u = $base . $u;
        }
        // filter wrong host
        if ($base && strpos($u, $base) !== 0) return;
        $links[$u] = true;
    };

    // 1) Absolute URLs already in page
    switch ($store) {
        case 'carrefour':
            if (preg_match_all('~https?://www\.carrefour\.fr/p/[a-z0-9\-\_]+~i', $html, $m)) {
                foreach ($m[0] as $u) { $links[$u] = true; }
            }
            break;
        case 'intermarche':
            if (preg_match_all('~https?://www\.intermarche\.com/produit/[a-z0-9\-\_]+~i', $html, $m)) {
                foreach ($m[0] as $u) { $links[$u] = true; }
            }
            break;
        case 'auchan':
            if (preg_match_all('~https?://www\.auchan\.fr/produit/[a-z0-9\-\_]+~i', $html, $m)) {
                foreach ($m[0] as $u) { $links[$u] = true; }
            }
            break;
        case 'monoprix':
            if (preg_match_all('~https?://www\.monoprix\.fr/(?:courses/)?produit/[a-z0-9\-\_]+~i', $html, $m)) {
                foreach ($m[0] as $u) { $links[$u] = true; }
            }
            break;
    }

    // 2) Relative HREFs in markup
    $rxRel = null;
    switch ($store) {
        case 'carrefour':   $rxRel = '~href=["\'](\/p\/[a-z0-9\-\_]+)~i'; break;
        case 'intermarche': $rxRel = '~href=["\'](\/produit\/[a-z0-9\-\_]+)~i'; break;
        case 'auchan':      $rxRel = '~href=["\'](\/produit\/[a-z0-9\-\_]+)~i'; break;
        case 'monoprix':    $rxRel = '~href=["\'](\/(?:courses\/)?produit\/[a-z0-9\-\_]+)~i'; break;
    }
    if ($rxRel && preg_match_all($rxRel, $html, $m)) {
        foreach ($m[1] as $u) { $push($u); }
    }

    // 3) JSON (Next.js, embedded state) – look for product paths or url fields
    $jsonPatterns = [];
    switch ($store) {
        case 'carrefour':
            $jsonPatterns = [
                '~"productUrl"\s*:\s*"(/p/[a-z0-9\-\_]+)"~i',
                '~"url"\s*:\s*"(/p/[a-z0-9\-\_]+)"~i',
                '~"href"\s*:\s*"(/p/[a-z0-9\-\_]+)"~i',
            ];
            break;
        case 'intermarche':
            $jsonPatterns = [
                '~"url"\s*:\s*"(/produit/[a-z0-9\-\_]+)"~i',
                '~"href"\s*:\s*"(/produit/[a-z0-9\-\_]+)"~i',
            ];
            break;
        case 'auchan':
            $jsonPatterns = [
                '~"url"\s*:\s*"(/produit/[a-z0-9\-\_]+)"~i',
                '~"href"\s*:\s*"(/produit/[a-z0-9\-\_]+)"~i',
            ];
            break;
        case 'monoprix':
            $jsonPatterns = [
                '~"url"\s*:\s*"(/(?:courses\/)?produit/[a-z0-9\-\_]+)"~i',
                '~"href"\s*:\s*"(/(?:courses\/)?produit/[a-z0-9\-\_]+)"~i',
            ];
            break;
    }
    foreach ($jsonPatterns as $rx) {
        if (preg_match_all($rx, $html, $m)) {
            foreach ($m[1] as $u) { $push($u); }
        }
    }

    // 4) De-dup and cap
    return array_slice(array_keys($links), 0, 10);
}

function score_candidate(string $title, string $url, array $features): int {
    $toks = norm_tokenize($title);
    $score = 0;
    if (!empty($features['brand']) && in_array($features['brand'], $toks, true)) $score += 3;
    if (!empty($features['form'])  && in_array($features['form'],  $toks, true)) $score += 2;
    if (!empty($features['doses']) && preg_match('~\b'.preg_quote((string)$features['doses'], '~').'\b~', $title)) $score += 4;
    if (!empty($features['kg'])    && preg_match('~\b'.preg_quote((string)round($features['kg'], 3), '~').'\b~', $title)) $score += 2;
    if (!empty($features['liters'])&& preg_match('~\b'.preg_quote((string)round($features['liters'], 2), '~').'\b~', $title)) $score += 2;
    // small bonus if url contains brand token
    if (!empty($features['brand']) && stripos($url, $features['brand']) !== false) $score += 1;
    return $score;
}

// ===== Routes =====

if (isset($_GET['action']) && $_GET['action'] === 'find_equivalents') {
    $seed = isset($_GET['seed']) ? (string)$_GET['seed'] : '';
    if ($seed === '') {
        respond(['ok'=>false,'error'=>'missing_seed']);
    }
    $worker = isset($_GET['worker']) ? trim((string)$_GET['worker']) : (getenv('SCRAPER_WORKER') ?: '');
    if ($worker === '') {
        respond(['ok'=>false,'error'=>'missing_worker','hint'=>'pass ?worker=https://xxxxx.ngrok-free.app']);
    }

    // 1) Scrape seed via normal pipeline (prefers worker /scrape) to get unit data and canonical title
    $meta = scrape($seed);
    $seedTitle = (string)($meta['title'] ?? '');
    $seedUnit  = is_array($meta['unit'] ?? null) ? $meta['unit'] : [];
    $feat = extract_features_from_title($seedTitle, $seedUnit);
    $query = build_query_from_features($feat, $seedTitle);

    // Build token list for scoring
    $tokens = [];
    if (!empty($feat['brand'])) $tokens[] = (string)$feat['brand'];
    if (!empty($feat['form']))  $tokens[] = (string)$feat['form'];
    if (!empty($feat['doses'])) $tokens[] = (string)$feat['doses'];

    // Target stores (exclude the seed's own store)
    $allowedStores = ['carrefour','intermarche','auchan','monoprix'];
    $seedStore = host_to_store($seed);

    // Allow runtime restriction via ?stores=carrefour,auchan ...
    if (isset($_GET['stores'])) {
        $req = array_filter(array_map('trim', explode(',', strtolower((string)$_GET['stores']))));
        $stores = array_values(array_intersect($allowedStores, $req));
        // Fallback sensible if param is invalid/empty
        if (empty($stores)) { $stores = ['carrefour']; }
    } else {
        // Test phase: focus Carrefour first
        $stores = ['carrefour'];
    }

    // Do not compare with the same seed store
    $stores = array_values(array_filter($stores, fn($s) => $s !== $seedStore));

    $matches = [];
    foreach ($stores as $store) {
        $searchUrl = store_search_url($store, $query);
        $cands = [];
        if ($searchUrl) {
            $base = preg_replace('~^(https?://[^/]+).*~', '$1', $searchUrl);

            // First try lightweight fetch (no attach), keep puzzle bypass enabled
            $wf = worker_fetch($worker, $searchUrl, $base, 35, ['nopuzzle' => true]);

            // If bot protection or 403, retry once with attach+autoclick
            if (!is_array($wf) || (($wf['code'] ?? 0) === 403) || (!empty($wf['bot_protection']))) {
                $wf = worker_fetch($worker, $searchUrl, $base, 45, [
                    'attach'    => true,
                    'autoclick' => true,
                    'nopuzzle'  => true,
                ]);
            }

            // If the worker already resolved to a product page, seed candidates with it
            $directProduct = null;
            if (is_array($wf) && !empty($wf['final_url'])) {
                $fu = (string)$wf['final_url'];
                switch ($store) {
                    case 'carrefour':
                        if (preg_match('~^https?://[^/]*carrefour\.fr/(?:p/|[^?#]*/p/)~i', $fu)) $directProduct = $fu;
                        break;
                    case 'intermarche':
                        if (preg_match('~^https?://[^/]*intermarche\.com/.+/(?:produit|p)/~i', $fu)) $directProduct = $fu;
                        break;
                    case 'auchan':
                        if (preg_match('~^https?://[^/]*auchan\.fr/.+/(?:p-\d+|produit|p/)~i', $fu)) $directProduct = $fu;
                        break;
                    case 'monoprix':
                        if (preg_match('~^https?://[^/]*monoprix\.fr/courses/.*/p/\d+~i', $fu)) $directProduct = $fu;
                        break;
                }
            }

            $html = is_array($wf) ? (string)($wf['html'] ?? '') : '';

            // EARLY EXIT: If $directProduct is set, **always** reuse the HTML we already fetched to avoid reopening the page
            if ($directProduct) {
                $wfBest = $wf; // reuse search fetch result (already resolved to product)

                $htmlBest = is_array($wfBest) ? (string)($wfBest['html'] ?? '') : '';
                $rowTitle = '';
                $rowPrice = null;
                $rowUnit  = null;

                if ($htmlBest !== '') {
                    $rowPrice = parse_price_only($htmlBest, $store);
                    $rowTitle = parse_title_only($htmlBest, $directProduct);
                }

                if ($rowTitle === '') {
                    $rowTitle = basename(parse_url($directProduct, PHP_URL_PATH) ?: '');
                }

                $bestRow = [
                    'url'   => $directProduct,
                    'title' => $rowTitle !== '' ? $rowTitle : 'Produit',
                    'price' => is_numeric($rowPrice) ? (float)$rowPrice : null,
                    'unit'  => $rowUnit,
                    'score' => 999,
                ];
                $matches[] = [
                    'store'      => $store,
                    'search_url' => $searchUrl,
                    'best'       => $bestRow,
                    'candidates' => [$bestRow],
                ];
                continue;
            }

            $candA = [];
            $candA = array_merge($candA, extract_candidates($store, $html, $searchUrl, $tokens));
            // Also try legacy extractor for safety, merge results
            $linksLegacy = extract_product_links_for_store($store, $html);
            foreach ($linksLegacy as $u) $candA[] = ['url'=>$u, 'score'=>0];
            // Dedup by URL but keep best base score (e.g., direct product seeded at 999)
            $base = [];
            foreach ($candA as $c) {
                $u  = $c['url'];
                $sc = (int)($c['score'] ?? 0);
                if (!isset($base[$u]) || $sc > $base[$u]) {
                    $base[$u] = $sc;
                }
            }

            // For each unique candidate link, fetch HTML once via worker, parse price+title locally, and compute final score
            // Define origin (referer) once
            $origin = preg_replace('~^(https?://[^/]+).*~', '$1', (string)$searchUrl);
            foreach ($base as $u => $baseScore) {
                // Candidate fetch: try light, then attach only if needed (reduces duplicate openings)
                $wfProd = worker_fetch($worker, $u, $origin, 35, ['nopuzzle' => true]);
                if (!is_array($wfProd) || (($wfProd['code'] ?? 0) === 403) || (!empty($wfProd['bot_protection'])) || empty($wfProd['html'])) {
                    $wfProd = worker_fetch($worker, $u, $origin, 45, [
                        'attach'    => true,
                        'autoclick' => true,
                        'nopuzzle'  => true,
                    ]);
                }
                $htmlP = is_array($wfProd) ? (string)($wfProd['html'] ?? '') : '';
                $rowPrice = null;
                $rowTitle = '';
                if ($htmlP !== '') {
                    $rowPrice = parse_price_only($htmlP, $store);
                    $rowTitle = parse_title_only($htmlP, $u);
                } else {
                    $rowTitle = basename(parse_url($u, PHP_URL_PATH) ?: '') ?: 'Produit';
                }
                $calcScore = score_candidate($rowTitle, $u, $feat);
                $finalScore = max($baseScore, $calcScore);

                $cands[] = [
                    'url'   => $u,
                    'title' => $rowTitle,
                    'price' => is_numeric($rowPrice) ? (float)$rowPrice : null,
                    'unit'  => null,
                    'score' => $finalScore,
                ];
            }
        }
        // pick best by score >=5
        usort($cands, fn($a,$b) => ($b['score'] <=> $a['score']));
        $best = null;
        foreach ($cands as $row) { if (($row['score'] ?? 0) >= 5) { $best = $row; break; } }

        $matches[] = [
            'store'      => $store,
            'search_url' => $searchUrl,
            'best'       => $best,
            'candidates' => $cands,
        ];
    }

    respond([
        'ok'    => true,
        'seed'  => [
            'url'      => $seed,
            'store'    => $seedStore,
            'title'    => $seedTitle,
            'price'    => (array_key_exists('price', $meta) && is_numeric($meta['price'])) ? (float)$meta['price'] : null,
            'currency' => (string)($meta['currency'] ?? 'EUR'),
            'unit'     => $seedUnit,
            'features' => $feat,
        ],
        'query'   => $query,
        'matches' => $matches,
    ]);
}

// Démo seed
if (isset($_GET['preset']) && $_GET['preset'] === 'coca175') {
    respond([
        'ok' => true,
        'results' => [
            ['url' => 'https://www.leclercdrive.fr/produit/coca-175l', 'title' => 'Coca‑Cola Original 1,75 L', 'price' => 2.38, 'currency' => 'EUR', 'seeded' => true],
            ['url' => 'https://www.carrefour.fr/p/coca-cola-175l',      'title' => 'Coca‑Cola 1,75 L',            'price' => 2.39, 'currency' => 'EUR', 'seeded' => true],
            ['url' => 'https://www.intermarche.com/produit/coca-175l',  'title' => 'Coca‑Cola 1,75 L',            'price' => 2.42, 'currency' => 'EUR', 'seeded' => true],
            ['url' => 'https://www.auchan.fr/produit/coca-175l',        'title' => 'Coca‑Cola 1,75 L',            'price' => 2.43, 'currency' => 'EUR', 'seeded' => true],
            ['url' => 'https://www.monoprix.fr/produit/coca-175l',      'title' => 'Coca‑Cola 1,75 L',            'price' => 2.65, 'currency' => 'EUR', 'seeded' => true],
        ]
    ]);
}

// Batch url[] ou url=
$urls = [];
if (isset($_GET['url'])) {
    $urls = is_array($_GET['url']) ? $_GET['url'] : [$_GET['url']];
}

if (!empty($urls)) {
    $results = [];
    foreach ($urls as $u) {
        $meta = scrape($u);
        $row = [
            'url'      => $u,
            'title'    => (string)($meta['title'] ?? ''),
            'price'    => array_key_exists('price', $meta) && is_numeric($meta['price']) ? (float)$meta['price'] : null,
            'currency' => (string)($meta['currency'] ?? 'EUR'),
            'source'   => (string)($meta['source'] ?? ''),
        ];
        if ($store = host_to_store($u)) {
            $row['store'] = $store;
        }
        if (!empty($meta['unit'])) {
            $row['unit'] = $meta['unit'];
        }
        if (!empty($meta['debug']) && isset($_GET['debug'])) {
            $row['debug'] = $meta['debug'];
        }
        $results[] = $row;
    }
    respond(['ok' => true, 'results' => $results]);
}

// Défaut
respond(['ok' => false, 'results' => [], 'error' => 'missing_parameters']);

function respond(array $payload, int $status = 200): void {
    http_response_code($status);
    $json = json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    if ($json === false) {
        http_response_code(500);
        echo '{"ok":false,"error":"json_encode_failed"}';
        exit;
    }
    echo $json;
    exit;
}