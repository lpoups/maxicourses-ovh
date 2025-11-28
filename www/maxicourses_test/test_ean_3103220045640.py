#!/usr/bin/env python3
"""Test pour vérifier si le problème persiste avec l'EAN 3103220045640"""
import subprocess
import sys
import os

EAN = "3103220045640"  # Haribo (autre produit)

cmd = [
    sys.executable,
    "/Users/laurentpoupet/Sites/maxicourses-ovh/www/maxicourses_test/pipeline/run_pipeline.py",
    "--ean",
    EAN,
    "--adapters",
    "leclerc",
]

env = os.environ.copy()
env["USE_CDP"] = "1"
env["LECLERC_NO_DELAY"] = "1"
env["PYTHONPATH"] = "/Users/laurentpoupet/Sites/maxicourses-ovh/www/maxicourses_test"

print("="*80)
print(f"TEST COLLECTE SOLO - EAN {EAN} (Haribo autre produit)")
print("="*80)
print(f"Commande: {' '.join(cmd)}\n")

proc = subprocess.run(cmd, env=env, capture_output=True, text=True)

print("STDOUT:")
print(proc.stdout)
print("\n" + "="*80)
print("Recherche de QUERY dans la sortie:")
print("="*80)

# Extraire et afficher la QUERY utilisée
import json
if proc.returncode == 0:
    # Trouver le fichier de résultat
    result_files = subprocess.run(
        ["ls", "-t", f"/Users/laurentpoupet/Sites/maxicourses-ovh/www/maxicourses_test/results/run-{EAN}-*.json"],
        capture_output=True,
        text=True,
        shell=True
    )
    if result_files.returncode == 0:
        latest = result_files.stdout.strip().split('\n')[0]
        if latest:
            with open(latest, 'r') as f:
                data = json.load(f)
                for result in data.get('adapter_results', []):
                    if result.get('adapter') == 'leclerc':
                        query = result.get('env', {}).get('QUERY')
                        ean_used = result.get('env', {}).get('EAN')
                        print(f"\n✓ EAN: {ean_used}")
                        print(f"✓ QUERY: {query}")
                        if query == ean_used:
                            print(f"\n❌ PROBLÈME: QUERY == EAN (recherche par EAN, ne fonctionne pas!)")
                        else:
                            print(f"\n✅ OK: QUERY != EAN (recherche par mots-clés)")

print(f"\nExit code: {proc.returncode}")
