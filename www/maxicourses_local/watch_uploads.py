#!/usr/bin/env python3
"""Simple watcher for barcode image uploads."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

from decode_ean import decode_image_to_ean

UPLOAD_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff'}
DEFAULT_ADAPTERS = [
    'carrefour_city',
    'carrefour_market',
    'carrefour_super',
    'auchan',
    'chronodrive',
    'leclerc',
    'intermarche',
]
EAN_REQUIRED_LENGTH = 13


def run_pipeline(ean: str, adapters: Iterable[str], headed: bool, results_dir: Path) -> int:
    """Invoke pipeline/run_pipeline.py for the given EAN."""
    pipeline = Path(__file__).resolve().parent / 'pipeline' / 'run_pipeline.py'
    cmd = [sys.executable, str(pipeline), '--ean', ean, '--results-dir', str(results_dir)]
    if headed:
        cmd.append('--headed')
    if adapters:
        cmd.extend(['--adapters', *adapters])

    env = os.environ.copy()
    env.setdefault('USE_CDP', '1')
    print(f"[INFO] Lancement pipeline: {' '.join(cmd)}")
    return subprocess.run(cmd, env=env).returncode


def watch_directory(
    directory: Path,
    adapters: Iterable[str],
    headed: bool,
    interval: float,
    results_root: Path,
    reprocess_existing: bool,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    processed: set[Path] = set()
    if not reprocess_existing:
        processed = {p for p in directory.iterdir() if p.is_file()}

    print(f"[INFO] Surveillance de {directory} (Ctrl+C pour arrêter)")
    try:
        while True:
            for path in directory.iterdir():
                if not path.is_file() or path in processed:
                    continue
                if path.suffix.lower() not in UPLOAD_EXTENSIONS:
                    continue

                print(f"[INFO] Nouvelle image détectée: {path.name}")
                ean = decode_image_to_ean(path)
                if not ean:
                    print(f"[WARN] Impossible de décoder {path.name}")
                    processed.add(path)
                    continue

                digits = ''.join(ch for ch in ean if ch.isdigit())
                if len(digits) != EAN_REQUIRED_LENGTH:
                    print(f"[WARN] EAN invalide ({digits or ean}) – {EAN_REQUIRED_LENGTH} chiffres requis")
                    processed.add(path)
                    continue

                timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
                results_dir = results_root / f'test-{digits}'
                exit_code = run_pipeline(digits, adapters, headed, results_dir)
                if exit_code == 0:
                    print(f"[OK] Collecte terminée pour EAN {digits} ({timestamp})")
                else:
                    print(f"[ERROR] Pipeline exit {exit_code} pour EAN {digits}")
                processed.add(path)

            time.sleep(max(0.5, interval))
    except KeyboardInterrupt:
        print("[INFO] Arrêt demandé (Ctrl+C)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watcher d'uploads EAN")
    parser.add_argument('--uploads-dir', default='uploads', help='Répertoire surveillé (relatif au script)')
    parser.add_argument('--results-root', default='results', help='Répertoire racine des résultats pipeline')
    parser.add_argument('--interval', type=float, default=2.0, help='Intervalle de scan en secondes')
    parser.add_argument('--adapters', nargs='*', default=DEFAULT_ADAPTERS, help='Adaptateurs à exécuter')
    parser.add_argument('--headed', action='store_true', help='Lancer la collecte en mode headed')
    parser.add_argument('--reprocess-existing', action='store_true', help='Traiter aussi les fichiers déjà présents')
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()
    base = Path(__file__).resolve().parent
    uploads_dir = (base / args.uploads_dir).resolve()
    results_root = (base / args.results_root).resolve()
    watch_directory(
        directory=uploads_dir,
        adapters=args.adapters,
        headed=args.headed,
        interval=args.interval,
        results_root=results_root,
        reprocess_existing=args.reprocess_existing,
    )
