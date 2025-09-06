<?php
declare(strict_types=1);

/**
 * Adapter local DEMO.
 * Remplace ces valeurs par l'appel à ton scrapper réel.
 * Retour: ['title'=>string,'price'=>float|null,'currency'=>'EUR']
 */
function mx_scrape(string $url): array {
    $host = strtolower(parse_url($url, PHP_URL_HOST) ?? '');
    $title = 'Produit';

    // Mappage démo aligné sur le preset coca175
    if (strpos($host, 'leclerc') !== false)      return ['title'=>$title, 'price'=>2.38, 'currency'=>'EUR'];
    if (strpos($host, 'carrefour') !== false)    return ['title'=>$title, 'price'=>2.39, 'currency'=>'EUR'];
    if (strpos($host, 'intermarche') !== false)  return ['title'=>$title, 'price'=>2.42, 'currency'=>'EUR'];
    if (strpos($host, 'auchan') !== false)       return ['title'=>$title, 'price'=>2.43, 'currency'=>'EUR'];
    if (strpos($host, 'monoprix') !== false)     return ['title'=>$title, 'price'=>2.65, 'currency'=>'EUR'];

    // Fallback
    $title = basename(parse_url($url, PHP_URL_PATH) ?: '') ?: 'Produit';
    return ['title'=>$title, 'price'=>null, 'currency'=>'EUR'];
}