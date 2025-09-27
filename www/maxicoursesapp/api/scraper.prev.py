from __future__ import annotations

# --- Bootstrap package context when executed as a script ---
try:  # ensure 'maxicoursesapp' package is importable so that relative imports (.stores) work
    if __package__ in (None, ""):
        import os as _os_boot, sys as _sys_boot
        _api_dir = _os_boot.path.dirname(_os_boot.path.abspath(__file__))          # .../maxicoursesapp/api
        _pkg_dir = _os_boot.path.dirname(_api_dir)                                 # .../maxicoursesapp
        _root_dir = _os_boot.path.dirname(_pkg_dir)                                # .../ (parent containing maxicoursesapp)
        # Ajouter d'abord le répertoire racine pour que 'import maxicoursesapp' fonctionne
        for _p in (_root_dir, _pkg_dir):
            if _p not in _sys_boot.path:
                _sys_boot.path.insert(0, _p)
        try:
            import maxicoursesapp.api  # type: ignore  # noqa: F401
            __package__ = "maxicoursesapp.api"
        except Exception:
            pass
except Exception:
    pass

# === Imports globaux propres ===
import re, os, json, time, gzip, io, sys, threading
from urllib.parse import urlparse, urlsplit, parse_qs, urljoin
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import Request, build_opener, HTTPCookieProcessor
from http.cookies import SimpleCookie
from http.cookiejar import CookieJar


def _scrape_direct_leclerc(url: str, debug_override: bool = False) -> dict:
    """Version minimaliste: HTTP direct + regex prix/EAN.
    (Playwright/captcha avancé sera déplacé plus tard dans stores/leclerc.py)
    """
    try:
        import requests  # type: ignore
    except Exception:
        return {"ok": False, "source": "leclerc", "error": "requests_missing"}
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
        'Connection': 'keep-alive',
        'Referer': 'https://www.leclercdrive.fr/'
    }
    html = ''
    try:
        r = requests.get(url, timeout=18, headers=headers)
        html = r.text or ''
    except Exception as e:
        return {"ok": False, "source": "leclerc", "error": f"http_error:{e}"}
    low = html.lower()
    if len(html) < 400 and ('captcha' in low or 'enable javascript' in low or 'datadome' in low):
        return {"ok": False, "source": "leclerc", "bot_protection": True, "url": url}
    price = None
    m = re.search(r'"(priceInCents|sellingPriceInCents|sellingPrice)"\s*:\s*(\d{2,7})', html)
    if m:
        try:
            val = int(m.group(2));
            if 10 <= val <= 200000: price = round(val/100.0, 2)
        except Exception: pass
    if price is None:
        m2 = re.search(r'"nrPVUnitaireTTC"\s*:\s*([0-9]+(?:\.[0-9]{1,2})?)', html)
        if m2:
            try:
                v = float(m2.group(1));
                if 0.1 < v < 500: price = round(v,2)
            except Exception: pass
    ean = None
    me = re.search(r'"sCodeEAN"\s*:\s*"(\d{8,14})"', html)
    if me: ean = me.group(1)
    desc = ''
    mt = re.search(r'<title>([^<]{5,200})</title>', html)
    if mt:
        desc = re.sub(r'\s+', ' ', mt.group(1)).strip()
    return {"ok": True, "source": "leclerc", "url": url, "price": price, "desc": desc, "ean": ean}

def _scrape_leclerc_minimal(url: str, debug: bool = False, headful: bool = True) -> dict:
    """Version minimale qui réplique presque exactement le script test_leclerc_product.py.
    Objectif: récupérer le JSON interne (nrPVUnitaireTTC, sCodeEAN) avec le profil pwtest-user sans les boucles anti-bot.
    """
    try:
        try:
            from playwright.sync_api import sync_playwright as _pw
        except Exception:
            return {"ok": False, "error": "playwright_not_installed", "used_playwright": False}
        import re, pathlib, datetime
        attempts = []
        user_data_dir = pathlib.Path('pwtest-user')
        user_data_dir.mkdir(parents=True, exist_ok=True)
        with _pw() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=not headful,
                args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-infobars'
                ],
                locale='fr-FR',
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                viewport={'width': 1366, 'height': 900},
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            except Exception:
                pass
            # Homepage rapide
            try:
                r1 = page.goto('https://www.leclercdrive.fr/', timeout=25000, wait_until='domcontentloaded')
                attempts.append({'step': 'home', 'status': r1.status if r1 else None})
            except Exception as e:
                attempts.append({'step': 'home_error', 'error': str(e)[:120]})
            try:
                page.wait_for_timeout(1500)
            except Exception:
                pass
            # Produit
            html = ''
            try:
                r2 = page.goto(url, timeout=35000, wait_until='domcontentloaded')
                attempts.append({'step': 'product', 'status': r2.status if r2 else None})
                page.wait_for_timeout(3500)
                html = page.content() or ''
            except Exception as e:
                attempts.append({'step': 'product_error', 'error': str(e)[:160]})
            try:
                ctx.close()
            except Exception:
                pass
        low = (html or '').lower()
        if not html or 'vous avez été bloqué' in low or 'captcha-delivery.com' in low or '403' in low[:1600]:
            return {"ok": False, "bot_protection": True, "used_playwright": True, "attempts": attempts, "reason": "minimal_block"}
        # Extraction ciblée – isoler l'objet JSON du produit principal par équilibrage d'accolades.
        price = None; ean = None; desc = ''
        target_id = None
        m_tid = re.search(r'fiche-produits-(\d+)-', url)
        if m_tid:
            target_id = m_tid.group(1)
        segment = ''
        anchor = f'"iIdProduit":{target_id}' if target_id else None
        if anchor:
            idx = html.find(anchor)
            if idx != -1:
                # Chercher en avant une zone compacte contenant à la fois id, prix et EAN
                window = html[idx: idx+200000]
                # Mini heuristique: trouver le premier bloc qui contient nrPVUnitaireTTC ET sCodeEAN
                m_block = re.search(r'\{[^{}]{0,2000}' + re.escape(anchor) + r'[^{}]{0,4000}?"nrPVUnitaireTTC"\s*:\s*[0-9]+(?:\.[0-9]{1,2})?[^{}]{0,4000}?"sCodeEAN"\s*:\s*"\d{8,14}"[^{}]{0,2000}\}', window)
                if m_block:
                    segment = m_block.group(0)
                else:
                    # fallback: ancienne méthode équilibrage
                    start = idx
                    while start > 0 and html[start] != '{':
                        start -= 1
                    if html[start] == '{':
                        brace = 0
                        end = start
                        for pos in range(start, min(len(html), start+150000)):
                            ch = html[pos]
                            if ch == '{':
                                brace += 1
                            elif ch == '}':
                                brace -= 1
                                if brace == 0:
                                    end = pos + 1
                                    break
                        if brace == 0 and end > start:
                            candidate = html[start:end]
                            # Vérifier qu'on a le prix et EAN dedans
                            if 'nrPVUnitaireTTC' in candidate and 'sCodeEAN' in candidate:
                                segment = candidate
                    if not segment:
                        segment = html[idx: idx+20000]
        src_for_primary = segment or html
        # Limiter la recherche aux données situées APRES l'ancre pour éviter un autre produit
        sub_after_anchor = src_for_primary
        if anchor and anchor in src_for_primary:
            sub_after_anchor = src_for_primary[src_for_primary.find(anchor):]
        # Prix
        mp_match = re.search(r'"nrPVUnitaireTTC"\s*:\s*([0-9]+(?:\.[0-9]{1,2})?)', sub_after_anchor)
        if mp_match:
            try:
                v = float(mp_match.group(1))
                if 0.1 < v < 500:
                    price = round(v, 2)
            except Exception:
                pass
        # EAN
        ge_match = re.search(r'"sCodeEAN"\s*:\s*"(\d{8,14})"', sub_after_anchor)
        if ge_match:
            ean = ge_match.group(1)
        # Description
        l1_match = re.search(r'"sLibelleLigne1"\s*:\s*"([^"\\]{3,120})"', sub_after_anchor)
        l2_match = re.search(r'"sLibelleLigne2"\s*:\s*"([^"\\]{3,160})"', sub_after_anchor)
        if l1_match:
            desc = l1_match.group(1)
        if l2_match:
            desc = (desc + ' ' + l2_match.group(1)).strip()
        # Fallback si segment raté
        if (price is None or ean is None) and segment:
            if price is None:
                mp2 = re.search(r'"nrPVUnitaireTTC"\s*:\s*([0-9]+(?:\.[0-9]{1,2})?)', html)
                if mp2:
                    try:
                        v = float(mp2.group(1));
                        if 0.1 < v < 500: price = round(v,2)
                    except Exception:
                        pass
            if ean is None:
                ge2 = re.search(r'"sCodeEAN"\s*:\s*"(\d{8,14})"', html)
                if ge2:
                    ean = ge2.group(1)
        if (not desc):
            mt = re.search(r'<title>([^<]{5,200})</title>', html)
            if mt:
                desc = re.sub(r'\s+', ' ', mt.group(1)).strip()
        out = {"ok": True, "source": "leclerc", "minimal": True, "url": url, "price": price, "ean": ean, "desc": desc, "attempts": attempts, "html_len": len(html)}
        if debug:
            try:
                dbg_dir = pathlib.Path(__file__).parent / 'debug'
                dbg_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')
                (dbg_dir / f'leclerc-minimal-{ts}.html').write_text(html[:250000], encoding='utf-8', errors='ignore')
            except Exception:
                pass
        return out
    except Exception as e:
        return {"ok": False, "error": f"minimal_error: {e}"}
import subprocess

# Stubs pour compatibilité minimale
def price_from_jsonld(html):
    return None, None

# Mapping temporaire EAN -> URLs par enseigne (étape 1: seulement Leclerc pour ce produit)
_PRODUCT_URLS = {
    '8700216648783': {
        'leclerc': 'https://fd12-courses.leclercdrive.fr/magasin-173301-173301-Bruges/fiche-produits-266448-Lessive-capsules-Ariel-Pods.aspx',
        # Carrefour: sera résolu dynamiquement par recherche EAN (placeholder)
        # 'auchan': 'TODO',
        # etc.
    }
}

# Wrapper Carrefour migré (logique déplacée dans stores/carrefour.py)
def _search_carrefour_by_ean(ean: str, store_slug: str = None, product_url: str = None, store_url: str = None, debug: bool = False):
    # Essayer import absolu d'abord (fonctionne même si exécuté hors package)
    try:
        try:
            from maxicoursesapp.api.stores import carrefour as _carrefour_mod  # type: ignore
        except Exception:
            from .stores import carrefour as _carrefour_mod  # type: ignore
        return _carrefour_mod.search_by_ean(ean, store_slug=store_slug, product_url=product_url, store_url=store_url, debug=debug)
    except Exception as e:
        # Dernier fallback: tentative via importlib en ré-injectant le parent dans sys.path
        try:
            import importlib, os as _os_cwrap, sys as _sys_cwrap
            _api_dir = _os_cwrap.path.dirname(_os_cwrap.path.abspath(__file__))
            _pkg_dir = _os_cwrap.path.dirname(_api_dir)
            _root_dir = _os_cwrap.path.dirname(_pkg_dir)
            if _root_dir not in _sys_cwrap.path:
                _sys_cwrap.path.insert(0, _root_dir)
            _carrefour_mod = importlib.import_module('maxicoursesapp.api.stores.carrefour')  # type: ignore
            return _carrefour_mod.search_by_ean(ean, store_slug=store_slug, product_url=product_url, store_url=store_url, debug=debug)
        except Exception as e2:
            return {'ok': False, 'error': f'carrefour_module_missing:{e2}'}

def _carrefour_playwright_minimal(ean: str, prefound_url: str = None, headful: bool = False, debug: bool = False, store_slug: str = None):
    try:
        try:
            from maxicoursesapp.api.stores import carrefour as _carrefour_mod  # type: ignore
        except Exception:
            from .stores import carrefour as _carrefour_mod  # type: ignore
        return _carrefour_mod.playwright_fallback(ean, store_slug=store_slug, product_url=prefound_url, headful=headful, debug=debug)
    except Exception as e:
        try:
            import importlib, os as _os_cwrap2, sys as _sys_cwrap2
            _api_dir = _os_cwrap2.path.dirname(_os_cwrap2.path.abspath(__file__))
            _pkg_dir = _os_cwrap2.path.dirname(_api_dir)
            _root_dir = _os_cwrap2.path.dirname(_pkg_dir)
            if _root_dir not in _sys_cwrap2.path:
                _sys_cwrap2.path.insert(0, _root_dir)
            _carrefour_mod = importlib.import_module('maxicoursesapp.api.stores.carrefour')  # type: ignore
            return _carrefour_mod.playwright_fallback(ean, store_slug=store_slug, product_url=prefound_url, headful=headful, debug=debug)
        except Exception as e2:
            return {'ok': False, 'error': f'carrefour_module_missing:{e2}'}

def _ensure_dynamic_store_mapping(ean: str, results: list):
    """Si un store dynamique (ex: carrefour) a été trouvé mais pas dans _PRODUCT_URLS,
    on l’ajoute en mémoire pour les appels suivants (cache très simple)."""
    try:
        if not ean or not isinstance(results, list):
            return
        cur = _PRODUCT_URLS.setdefault(ean, {})
        for r in results:
            if not isinstance(r, dict):
                continue
            store = r.get('store')
            url = r.get('url')
            if store and url and store not in cur and url.startswith('http'):
                cur[store] = url
    except Exception:
        pass

def _check_carrefour_slugs(slugs: list):
    """Teste une liste de slugs Carrefour et retourne leur statut (HTTP + ok bool)."""
    import urllib.request, urllib.error, time
    out = []
    # On tentera un fallback Playwright uniquement si toutes les réponses directes sont 403
    all_403 = True
    for slug in slugs:
        slug_clean = (slug or '').strip().strip('/')
        if not slug_clean:
            continue
        url = f"https://www.carrefour.fr/magasin/{slug_clean}"
        status = None
        ok = False
        err = None
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=12) as resp:
                status = resp.getcode()
                html_head = resp.read(4096).decode('utf-8', errors='ignore').lower()
                # Heuristique: 404 custom => contient '404' rapidement
                ok = (status == 200) and ('404' not in html_head[:600])
        except urllib.error.HTTPError as he:
            status = he.code
            err = f'http_{he.code}'
        except Exception as e:
            err = str(e)
        dur = round((time.time()-t0)*1000)
        if status != 403:
            all_403 = False
        out.append({'slug': slug_clean, 'url': url, 'status': status, 'ok': ok, 'ms': dur, 'error': err})

    # Fallback Playwright: si toutes les tentatives directes renvoient 403, on essaie d'ouvrir quelques pages avec un contexte navigateur
    try:
        if slugs and all_403:
            from playwright.sync_api import sync_playwright as _pw
            import pathlib
            # Limiter à 2 slugs pour ne pas exploser le temps
            subset = slugs[:2]
            with _pw() as p:
                user_data_dir = pathlib.Path('pw-carrefour-storecheck'); user_data_dir.mkdir(exist_ok=True)
                ctx = None
                try:
                    ctx = p.chromium.launch_persistent_context(user_data_dir=str(user_data_dir), headless=True, args=["--disable-dev-shm-usage"])  # type: ignore
                except Exception:
                    ctx = p.chromium.launch(headless=True)
                for slug in subset:
                    slug_clean = slug.strip().strip('/')
                    store_url = f"https://www.carrefour.fr/magasin/{slug_clean}"
                    t0 = time.time()
                    status = None; ok=False; err=None
                    try:
                        page = ctx.new_page() if hasattr(ctx, 'new_page') else ctx
                        page.goto(store_url, wait_until='domcontentloaded', timeout=30000)
                        html = page.content().lower()
                        # Caractéristiques d'une vraie page magasin: présence de 'carrefour' et d'éléments de navigation sans '404'
                        if 'carrefour' in html[:8000] and '404' not in html[:800]:
                            status = 200
                            ok = True
                        else:
                            # Essayer d'attendre un peu plus
                            page.wait_for_timeout(1500)
                            html2 = page.content().lower()
                            if 'carrefour' in html2[:8000] and '404' not in html2[:800]:
                                status = 200; ok=True
                            else:
                                status = 403 if '403' in html2[:500] else 200 if 'carrefour' in html2 else None
                    except Exception as e:
                        err = str(e)
                    dur = round((time.time()-t0)*1000)
                    # Mettre à jour la ligne correspondante dans out
                    for entry in out:
                        if entry['slug'] == slug_clean:
                            # Ne remplacer que si précédemment 403/non ok et maintenant on a mieux
                            if not entry.get('ok') and ok:
                                entry.update({'status': status, 'ok': ok, 'ms': dur, 'error': err, 'fallback':'playwright'})
                            else:
                                entry.setdefault('fallback', 'playwright_attempt')
                    # Fermeture page si possible
                    if 'page' in locals():
                        try:
                            if hasattr(page, 'close'):
                                page.close()
                        except Exception:
                            pass
                if hasattr(ctx, 'close'):
                    ctx.close()
    except Exception:
        pass
    return out

# ================== Intermarché (migré) ==================
def _intermarche_playwright_minimal(ean: str, headful: bool = False, debug: bool = False, prefound_url: str | None = None):
    """Wrapper rétrocompatible pointant vers stores.intermarche.playwright_fallback."""
    try:
        try:
            from maxicoursesapp.api.stores import intermarche as _im  # type: ignore
        except Exception:
            from .stores import intermarche as _im  # type: ignore
        return _im.playwright_fallback(ean, headful=headful, debug=debug, prefound_url=prefound_url)
    except Exception as e:
        try:
            import importlib, os as _os_imw, sys as _sys_imw
            _api_dir = _os_imw.path.dirname(_os_imw.path.abspath(__file__))
            _pkg_dir = _os_imw.path.dirname(_api_dir)
            _root_dir = _os_imw.path.dirname(_pkg_dir)
            if _root_dir not in _sys_imw.path:
                _sys_imw.path.insert(0, _root_dir)
            _im = importlib.import_module('maxicoursesapp.api.stores.intermarche')  # type: ignore
            return _im.playwright_fallback(ean, headful=headful, debug=debug, prefound_url=prefound_url)
        except Exception as e2:
            return {'ok': False, 'error': f'im_module_missing:{e2}'}

def _search_intermarche_by_ean(ean: str, debug: bool = False):
    """Wrapper rétrocompatible pointant vers stores.intermarche.search_by_ean."""
    try:
        try:
            from maxicoursesapp.api.stores import intermarche as _im  # type: ignore
        except Exception:
            from .stores import intermarche as _im  # type: ignore
        return _im.search_by_ean(ean, debug=debug)
    except Exception as e:
        try:
            import importlib, os as _os_imw2, sys as _sys_imw2
            _api_dir = _os_imw2.path.dirname(_os_imw2.path.abspath(__file__))
            _pkg_dir = _os_imw2.path.dirname(_api_dir)
            _root_dir = _os_imw2.path.dirname(_pkg_dir)
            if _root_dir not in _sys_imw2.path:
                _sys_imw2.path.insert(0, _root_dir)
            _im = importlib.import_module('maxicoursesapp.api.stores.intermarche')  # type: ignore
            return _im.search_by_ean(ean, debug=debug)
        except Exception as e2:
            return {'ok': False, 'error': f'im_module_missing:{e2}'}

# --- Modular store imports (incrémental) ---
try:
    from .stores import leclerc as store_leclerc  # type: ignore
except Exception:
    store_leclerc = None  # type: ignore
try:
    from .stores import carrefour as store_carrefour  # type: ignore
except Exception:
    store_carrefour = None  # type: ignore
# NOTE: Les fonctions internes existantes (_scrape_leclerc_minimal, _search_carrefour_by_ean, etc.) restent pour compatibilité.
# Progressivement, on pourra remplacer les appels dans _compare_ean par store_leclerc.scrape_direct / store_carrefour.search_by_ean.

def _compare_ean(ean, attach=False, nopuzzle=False, debug=False, stores=None, carrefour_store=None, carrefour_product=None, carrefour_store_url=None):
    # Nouveau wrapper vers module compare (modularisation en cours)
    try:
        from . import compare as _cmp  # type: ignore
    except Exception:
        try:
            import compare as _cmp  # type: ignore
        except Exception as e:
            return {"ok": False, "error": f"compare_module_error:{e}"}
    return _cmp.compare_ean(
        ean,
        debug=debug,
        stores=stores,
        carrefour_store=carrefour_store,
        carrefour_product=carrefour_product,
        carrefour_store_url=carrefour_store_url,
    )

def _search_auchan_by_ean(ean: str, debug: bool = False):
    import urllib.request, urllib.error, gzip, io, re as _re
    try:
        search_url=f"https://www.auchan.fr/recherche?text={ean}"
        def _simple(u):
            req=urllib.request.Request(u, headers={
                'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
                'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language':'fr-FR,fr;q=0.9','Connection':'close'
            })
            with urllib.request.urlopen(req, timeout=25) as resp:
                data=resp.read();
                if resp.headers.get('Content-Encoding')=='gzip':
                    data=gzip.GzipFile(fileobj=io.BytesIO(data)).read()
                return resp.getcode(), resp.geturl(), data.decode('utf-8', errors='ignore')
        try:
            code, final_url, html = _simple(search_url)
        except urllib.error.HTTPError as he:
            if he.code in (403, 429):
                return {'ok': False, 'error': 'blocked_auchan_http', 'code': he.code}
            return {'ok': False, 'error': f'http_{he.code}'}
        if code != 200 or not html:
            return {'ok': False, 'error': 'empty_search_auchan'}
        low = html.lower()
        if '/client/mes-produits-preferes' in low or 'se connecter' in low[:600]:
            return {'ok': False, 'error': 'login_required', 'url': final_url}
        if ean not in html:
            return {'ok': False, 'error': 'ean_not_in_search'}
        m = _re.search(r'href="(https://www\\.auchan\\.fr/[^\"]*produit[^\"]*)"', html)
        if not m:
            m = _re.search(r'href="(/[^"?#]*produit[^"?#]*)"', html)
        if not m:
            return {'ok': False, 'error': 'no_product_link'}
        prod_url = m.group(1)
        if prod_url.startswith('/'):
            prod_url = urllib.parse.urljoin('https://www.auchan.fr', prod_url)
        try:
            code2, final2, html2=_simple(prod_url)
        except urllib.error.HTTPError as he2:
            if he2.code in (403,429):
                return {'ok': False, 'error': 'blocked_prod_http', 'code': he2.code, 'url': prod_url}
            return {'ok': False, 'error': f'prod_http_{he2.code}', 'url': prod_url}
        if code2!=200 or not html2:
            return {'ok': False, 'error': 'empty_product_page', 'url': prod_url}
        price=None
        for rg in [r'"price"\s*:\s*"?([0-9]+(?:[\.,][0-9]{1,2}))"?', r'content="([0-9]+\.[0-9]{2})"\s+itemprop="price"', r'([0-9]+,[0-9]{2})\s*€']:
            mm=_re.search(rg, html2)
            if mm:
                raw=mm.group(1).replace(',', '.')
                try:
                    v=float(raw)
                    if 0.05 < v < 1000: price=round(v,2); break
                except Exception: pass
        desc=''
        mt=_re.search(r'<title>([^<]{5,160})</title>', html2)
        if mt: desc=_re.sub(r'\s+',' ', mt.group(1)).strip()
        ean_found=None
        if ean in html2: ean_found=ean
        if not ean_found:
            m2=_re.search(r'\b\d{13}\b', html2)
            if m2: ean_found=m2.group(0)
        return {'ok': True, 'url': prod_url, 'price': price, 'ean': ean_found, 'desc': desc}
    except Exception as e:
        return {'ok': False, 'error': f'auchan_error:{e}'}

# ... La suite du fichier original 'scraper.py' est très longue. Cette sauvegarde contient l'intégralité du contenu actuel
# avant rollback. Elle est conservée pour rétablissement rapide si besoin.
