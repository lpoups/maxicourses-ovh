#!/usr/bin/env python3
"""Wrapper appliquant la méthode Carrefour Market définie dans collection_mandate."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from collection_mandate import get_method

ROOT = Path(__file__).resolve().parent
MANDATE = get_method("carrefour_market")
TRACE_FILES = [ROOT.parent / 'traces' / name for name in MANDATE.trace_files]


def parse_payload(stdout: str) -> tuple[bool, dict]:
    if not stdout:
        return False, {}
    start = stdout.find('{')
    end = stdout.rfind('}')
    if start == -1 or end == -1 or end <= start:
        return False, {}
    snippet = stdout[start : end + 1]
    try:
        data = json.loads(snippet)
    except json.JSONDecodeError:
        try:
            data = json.loads(snippet.replace('\r', ' ').replace('\n', ' '))
        except json.JSONDecodeError:
            return False, {}
    status = data.get('status')
    if status != 'OK':
        return True, data
    expected = (MANDATE.store_hint or "").lower()
    store = (data.get('store') or '').lower()
    note = data.get('note')
    store_ok = expected and expected in store and not note
    return store_ok, data


def run_fetch(env):
    return subprocess.run(
        [sys.executable, 'fetch_carrefour_price.py'],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def emit_payload(data) -> None:
    print(json.dumps(data, ensure_ascii=False))


def replay_traces(env) -> None:
    for trace in TRACE_FILES:
        if not trace.exists():
            continue
        subprocess.run(
            [sys.executable, 'replay_leclerc_navigation.py', str(trace)],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description='Fetch Carrefour Market price via CDP (Market Bordeaux Fondaudège).')
    parser.add_argument('--ean', dest='ean', default=os.environ.get('EAN'), help='EAN du produit à rechercher')
    parser.add_argument('--query', dest='query', default=os.environ.get('QUERY'), help='Requête texte à saisir sur Carrefour')
    parser.add_argument('--headless', dest='headless', default=os.environ.get('HEADLESS', '0'))
    args = parser.parse_args(argv)

    env = os.environ.copy()
    if args.ean:
        env['EAN'] = args.ean
    if args.query:
        env['QUERY'] = args.query
    env.setdefault('USE_CDP', '1')
    env['HEADLESS'] = args.headless
    env['STORE_QUERY'] = MANDATE.store_hint
    env['CARREFOUR_STATE_VARIANT'] = 'carrefour_market'

    if TRACE_FILES:
        replay_traces(env)

    initial = run_fetch(env)

    success, data = parse_payload(initial.stdout)
    if success:
        emit_payload(data)
        if initial.stderr:
            print(initial.stderr, file=sys.stderr, end="")
        return initial.returncode

    replay_traces(env)

    if initial.stderr:
        print(initial.stderr, file=sys.stderr, end="")

    retry = run_fetch(env)
    retry_success, retry_data = parse_payload(retry.stdout)
    if retry_success:
        emit_payload(retry_data)
    else:
        if retry.stdout:
            print(retry.stdout, end="")
        if retry.stderr:
            print(retry.stderr, file=sys.stderr, end="")
    return retry.returncode


if __name__ == '__main__':
    sys.exit(run(sys.argv[1:]))
