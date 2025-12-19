import json
import re

# Simulated output from log
# "store": "TRIER : Pertinence 1,09€ Chewing-Gum Menthe Verte Sans Sucres \n FREEDENT REFRESHERS ..."
raw_output = r"""Checking for Turnstile/Cloudflare challenge...
{"status": "OK", "price": "1,09", "store": "TRIER : Pertinence 1,09€ Chewing-Gum Menthe Verte Sans Sucres \nFREEDENT REFRESHERS la boîte de 8 cubes Les produits ont bien été chargés Vous consultez 1 des 1 produits \nTrouver un magasin Obtenir de l'aide Télécharger l'application Consulter la FAQ En ce moment Promotions \nBlack Friday Calendrier de l'avent Jouets de Noël 2025 Chocolats de Noël Sapin de Noël Repas de Noël Menus \nde Noël TV Samsung Aspirat...", "title": "Chewing-Gum Menthe Verte Sans Sucres FREEDENT REFRESHERS", "quantity": "18g", "unit_price": "60.89 € / KG", "url": "https://www.carrefour.fr/p/chewing-gum-menthe-verte-sans-sucres-freedent-refreshers-4009900540865"}
"""

def parse(stdout):
    print(f"RAW: {stdout!r}")
    lines = stdout.strip().splitlines()
    data = None
    
    # Try strict
    try:
        data = json.loads(stdout)
        print("STRICT: Success")
        return data
    except Exception as e:
        print(f"STRICT: Failed ({e})")
    
    # Try Regex
    try:
        clean_stdout = stdout.strip()
        start = clean_stdout.find("{")
        end = clean_stdout.rfind("}")
        if start != -1 and end != -1:
            candidate_str = clean_stdout[start:end+1]
            print(f"CANDIDATE: {candidate_str!r}")
            try:
                data = json.loads(candidate_str)
                print("REGEX: Success")
                return data
            except Exception as e:
                print(f"REGEX: Failed ({e})")
                # Try finding where it fails
                pass
    except:
        pass
    
    return None

res = parse(raw_output)
print("RESULT:", res)
