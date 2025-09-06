<?php
error_reporting(E_ALL);
ini_set('display_errors','1');
header('Content-Type: text/plain; charset=utf-8');

echo "PHP_VERSION=" . PHP_VERSION . "\n";
echo "proc_open=" . (function_exists('proc_open') ? 'yes' : 'no') . "\n";
echo "disable_functions=" . ini_get('disable_functions') . "\n";

$whichPy = @shell_exec('which python3 2>/dev/null');
echo "which_python3=" . trim((string)$whichPy) . "\n";