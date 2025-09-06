<?php
// Maxicourses — Bridge PHP -> Python scraper
// Usage: /maxicoursesapp/api/price_bridge.php?url=<URL_PRODUIT>

declare(strict_types=1);
header('Content-Type: application/json; charset=utf-8');

$url = isset($_GET['url']) ? trim((string)$_GET['url']) : '';
if ($url === '') {
    echo json_encode(['ok' => false, 'error' => 'missing url']);
    exit;
}
if (!filter_var($url, FILTER_VALIDATE_URL)) {
    echo json_encode(['ok' => false, 'error' => 'invalid url']);
    exit;
}

$host = strtolower(parse_url($url, PHP_URL_HOST) ?: '');
$allowed = [
    'leclercdrive.fr', 'fd12-courses.leclercdrive.fr',
    'carrefour.fr', 'www.carrefour.fr',
    'auchan.fr', 'www.auchan.fr',
    'intermarche.com', 'www.intermarche.com',
    'monoprix.fr', 'www.monoprix.fr',
];
$okHost = false;
foreach ($allowed as $h) {
    if (substr($host, -strlen($h)) === $h) { $okHost = true; break; }
}
if (!$okHost) {
    echo json_encode(['ok' => false, 'error' => 'host not allowed', 'host' => $host]);
    exit;
}

$py = '/Users/laurentpoupet/venv/bin/python'; // adapte si besoin
$script = __DIR__ . '/leclerc_price_scraper.py';
if (!is_file($script)) {
    echo json_encode(['ok' => false, 'error' => 'script missing']);
    exit;
}

$cmd = escapeshellarg($py) . ' ' . escapeshellarg($script) . ' ' . escapeshellarg($url);
$env = [
    'LANG' => 'C.UTF-8',
    'LC_ALL' => 'C.UTF-8',
    'PYTHONIOENCODING' => 'utf-8',
];
$desc = [0 => ['pipe','r'], 1 => ['pipe','w'], 2 => ['pipe','w']];
$proc = proc_open($cmd, $desc, $pipes, __DIR__, $env);
if (!is_resource($proc)) {
    echo json_encode(['ok' => false, 'error' => 'proc_open failed']);
    exit;
}
fclose($pipes[0]);
$stdout = stream_get_contents($pipes[1]); fclose($pipes[1]);
$stderr = stream_get_contents($pipes[2]); fclose($pipes[2]);
$code = proc_close($proc);

if ($code !== 0) {
    echo json_encode(['ok' => false, 'error' => 'python failed', 'code' => $code, 'stderr' => $stderr, 'stdout' => $stdout]);
    exit;
}

$data = json_decode($stdout, true);
if (!is_array($data)) {
    echo json_encode(['ok' => false, 'error' => 'bad json', 'stdout' => $stdout]);
    exit;
}

echo json_encode($data, JSON_UNESCAPED_UNICODE);
