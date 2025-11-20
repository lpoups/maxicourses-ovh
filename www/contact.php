<?php
header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST');
header('Access-Control-Allow-Headers: Content-Type');

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405);
    echo json_encode(['status' => 'error', 'message' => 'Méthode non autorisée.']);
    exit;
}

$input = json_decode(file_get_contents('php://input'), true);
$lastname = trim($input['lastname'] ?? '');
$firstname = trim($input['firstname'] ?? '');
$phone = trim($input['phone'] ?? '');
$message = trim($input['message'] ?? '');

if ($lastname === '' || $firstname === '' || $phone === '' || $message === '') {
    http_response_code(422);
    echo json_encode(['status' => 'error', 'message' => 'Tous les champs sont obligatoires.']);
    exit;
}

$subject = 'Question site Maxicourses';
$body = "Nom : {$lastname}\nPrénom : {$firstname}\nTéléphone : {$phone}\n\n{$message}";
$from = 'contact@maxicourses.fr';
$headers = [
    'From: Maxicourses <' . $from . '>',
    'Reply-To: ' . $from,
    'Content-Type: text/plain; charset=UTF-8'
];

ini_set('sendmail_from', $from);
$sent = @mail('invest@maxicourses.fr', $subject, $body, implode("\r\n", $headers), '-f' . $from);

if ($sent) {
    echo json_encode(['status' => 'ok']);
} else {
    http_response_code(500);
    echo json_encode(['status' => 'error', 'message' => 'Le serveur n\'arrive pas à envoyer l\'email.']);
}
