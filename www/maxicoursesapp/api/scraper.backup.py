from __future__ import annotations
def _scrape_direct_leclerc(url: str, debug_override: bool = False) -> dict:
    """Scraping direct (requests) d'une fiche produit Leclerc.
    Retourne {ok, source, url, price, desc, ean}.
    Version stable après nettoyage (sans code orphelin).
    """
    import re, json as _json, pathlib, datetime, os as _os, time as _time
    import random
    try:
        import requests  # type: ignore
    except Exception:
        requests = None
    if not requests:
        return {"ok": False, "source": "leclerc", "error": "requests_missing"}
    attempt_meta = []
    UA_POOL = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    ]
    base_referer = 'https://www.leclercdrive.fr/'
    session = requests.Session()
    if '_detect_bot' in globals():
        _detect = globals()['_detect_bot']
    else:
        def _detect(html: str) -> bool:
            h = (html or '').lower()
            return 'captcha' in h or 'enable javascript' in h or 'datadome' in h
    try:
        html = ''
        bot_protection = False
        # Warm-up homepage
        try:
            _warm_ua = random.choice(UA_POOL)
            w_headers = {
                'User-Agent': _warm_ua,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'fr-FR,fr;q=0.9',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Cache-Control': 'no-cache',
            }
            w_resp = session.get(base_referer, timeout=10, headers=w_headers)
            attempt_meta.append({'attempt': 'warmup', 'status': w_resp.status_code, 'len': len(w_resp.text or '')})
        except Exception as _e:
            attempt_meta.append({'attempt': 'warmup', 'error': str(_e)[:120]})
        # Direct attempts
        for attempt in range(1, 3):
            ua = random.choice(UA_POOL)
            headers = {
                'User-Agent': ua,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.6,en;q=0.5',
                'Referer': base_referer,
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Pragma': 'no-cache',
                'Cache-Control': 'no-cache'
            }
            try:
                resp = session.get(url, timeout=18, headers=headers)
                html = resp.text or ''
                bot_protection = _detect(html)
                attempt_meta.append({'attempt': attempt, 'status': resp.status_code, 'len': len(html), 'bot': bot_protection})
                if not bot_protection and resp.status_code == 200 and len(html) > 500:
                    break
            except Exception as _e:
                attempt_meta.append({'attempt': attempt, 'error': str(_e)[:120]})
            _time.sleep(0.6)
        # Fallback fetch_raw_with_meta
        if (bot_protection or len(html) < 600) and 'fetch_raw_with_meta' in globals():
            try:
                code, final_url, html2 = globals()['fetch_raw_with_meta'](url, base_referer)
                if html2 and len(html2) > len(html):
                    html = html2
                bot_protection = _detect(html)
                attempt_meta.append({'attempt': 'fallback_raw', 'status': code, 'len': len(html), 'bot': bot_protection})
            except Exception as _e:
                attempt_meta.append({'attempt': 'fallback_raw', 'error': str(_e)[:120]})
        if bot_protection:
            return {'ok': False, 'source': 'leclerc', 'url': url, 'bot_protection': True, 'attempts': attempt_meta, 'reason': 'bot_protection_detected'}
        debug_mode = ('MAXI_DEBUG' in _os.environ) or debug_override or ('debug=1' in url.lower())
        debug_path = None
        if debug_mode:
            dbg_dir = pathlib.Path(__file__).parent / 'debug'
            try:
                dbg_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')
                debug_path = dbg_dir / f'leclerc-{ts}.html'
                debug_path.write_text(html[:2_000_000], encoding='utf-8', errors='ignore')
            except Exception:
                debug_path = None
        # Price extraction
        price = None
        for m in re.finditer(r'"(priceInCents|sellingPriceInCents|sellingPrice)"\s*:\s*(\d{2,7})', html):
            try:
                val = int(m.group(2))
                if 10 <= val <= 200000:
                    price = round(val / 100.0, 2)
                    break
            except Exception:
                pass
        if price is None:
            m = re.search(r'"nrPVUnitaireTTC"\s*:\s*([0-9]+(?:\.[0-9]{1,2})?)', html)
            if m:
                try:
                    v = float(m.group(1))
                    if 0.1 < v < 500:
                        price = round(v, 2)
                except Exception:
                    pass
        if price is None:
            m = re.search(r'"price"\s*:\s*"?([0-9]+,[0-9]{2})"?', html)
            if m:
                try:
                    price = float(m.group(1).replace(',', '.'))
                except Exception:
                    pass
        if price is None:
            m = re.search(r'"(?:priceTtc|price_ttc|prixTtc|prix)"\s*:\s*"?([0-9]+,[0-9]{2})"?', html)
            if m:
                try:
                    price = float(m.group(1).replace(',', '.'))
                except Exception:
                    pass
        if price is None:
            for blk in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>', html, re.I):
                b2 = re.sub(r',\s*([}\]])', r'\1', blk.strip())
                try:
                    data = _json.loads(b2)
                except Exception:
                    continue
                stack = [data]
                while stack:
                    cur = stack.pop()
                    if isinstance(cur, dict):
                        if cur.get('@type') == 'Product':
                            off = cur.get('offers') or {}
                            if isinstance(off, dict):
                                p = off.get('price') or off.get('lowPrice')
                                try:
                                    if p:
                                        pv = float(str(p).replace(',', '.'))
                                        if 0.1 < pv < 500:
                                            price = pv
                                            break
                                except Exception:
                                    pass
                        for v in cur.values():
                            if isinstance(v, (dict, list)):
                                stack.append(v)
                    elif isinstance(cur, list):
                        for v in cur:
                            if isinstance(v, (dict, list)):
                                stack.append(v)
                if price is not None:
                    break
        if price is None:
            for pat in [r'<span[^>]*class="[^"]*(?:prix|price)[^"]*"[^>]*>([0-9]+,[0-9]{2}) ?€</span>', r'([0-9]+,[0-9]{2}) ?€']:
                m = re.search(pat, html)
                if m:
                    try:
                        price = float(m.group(1).replace(',', '.'))
                        break
                    except Exception:
                        pass
        # Description
        desc = ''
        for pat in [
            r'<h1[^>]*class="[^"]*(?:titre|title|product-name)[^"]*"[^>]*>(.*?)</h1>',
            r'<h1[^>]*>(.*?)</h1>',
            r'<title>(.*?)</title>',
            r'<div[^>]*class="fiche-produit__description"[^>]*>(.*?)</div>',
            r'<div[^>]*class="description"[^>]*>(.*?)</div>',
            r'<meta name="description" content="([^"]+)"',
            r'alt="([^"]+)"[^>]*class="[^"]*(?:product|visuel)"',
        ]:
            m = re.search(pat, html, re.S)
            if m:
                desc_raw = m.group(1)
                desc = re.sub('<[^<]+?>', ' ', desc_raw)
                desc = re.sub(r'\s+', ' ', desc).strip()
                break
        # EAN
        ean = None
        for pat in [
            r'(?i)EAN\s*:?\s*</span>\s*<span[^>]*>(\d{8,14})</span>',
            r'(?i)>\s*EAN\s*:?\s*(\d{8,14})<',
            r'(?i)code(?:-| )?barres\s*:?\s*(\d{8,14})',
            r'(?i)"ean"\s*:\s*"?(\d{8,14})"?',
            r'(?i)"gtin13"\s*:\s*"?(\d{8,14})"?',
            r'(?i)"gtin"\s*:\s*"?(\d{8,14})"?',
            r'itemprop="gtin13"[^>]*content="(\d{8,14})"',
            r'data-(?:ean|gtin13|gtin)="(\d{8,14})"',
        ]:
            m = re.search(pat, html)
            if m:
                ean = m.group(1)
                break
        if ean is None:
            m = re.search(r'"sCodeEAN"\s*:\s*"(\d{8,14})"', html)
            if m:
                ean = m.group(1)
        if ean is None and 'extract_ean_generic' in globals():
            try:
                ean = globals()['extract_ean_generic'](html)
            except Exception:
                pass
        if (not desc or len(desc) < 5):
            m1 = re.search(r'"sLibelleLigne1"\s*:\s*"([^\"]{3,120})"', html)
            if m1:
                part1 = m1.group(1)
                m2 = re.search(r'"sLibelleLigne2"\s*:\s*"([^\"]{3,160})"', html)
                if m2:
                    desc = (part1 + ' ' + m2.group(1)).strip()
                else:
                    desc = part1.strip()
        if price is None:
            m = re.search(r'([0-9]+,[0-9]{2})\s*€', html)
            if m:
                try:
                    price = float(m.group(1).replace(',', '.'))
                except Exception:
                    pass
        out = {"ok": True, "source": "leclerc", "url": url, "price": price, "desc": desc, "ean": ean, "attempts": attempt_meta}
        if not debug_path and (price is None or ean is None):
            try:
                dbg_dir = pathlib.Path(__file__).parent / 'debug'
                dbg_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')
                auto_path = dbg_dir / f'leclerc-autodump-{ts}.html'
                auto_path.write_text(html[:200000], encoding='utf-8', errors='ignore')
                debug_path = auto_path
            except Exception:
                debug_path = None
        if debug_path:
            out['debug_dump'] = str(debug_path)
        return out
    except Exception as e:
        return {"ok": False, "source": "leclerc", "error": f"leclerc scrape error: {e}"}
    
def _scrape_leclerc_headless(url: str, debug: bool = False, headful_override: bool = False) -> dict:
    """Tentative de scraping Leclerc via Playwright headless.
    Nécessite: pip install playwright && playwright install chromium
    Retourne {ok, price, desc, ean, html_len, used_playwright, ...} ou bot_protection.
    """
    try:
        try:
            from playwright.sync_api import sync_playwright as _pw_sync
        except Exception:
            return {"ok": False, "used_playwright": False, "error": "playwright_not_installed"}
        import re as _re, time as _t, json as _json, pathlib, datetime, random, os as _os
        attempts = []
        html = ''
        state_dir = pathlib.Path(__file__).parent / 'debug'
        state_dir.mkdir(parents=True, exist_ok=True)
        state_file = state_dir / 'leclerc-playwright-state.json'
        # Contexte persistant entre appels pour réutiliser cookies DataDome
        with _pw_sync() as p:
            headful_env = _os.environ.get('HEADFUL') in ('1','true','yes') or headful_override
            headless = not headful_env
            # IMPORTANT: réutilise le profil déjà initialisé par test_leclerc_product.py
            # (cookies/DataDome potentiellement validés). Si le dossier n'existe pas, on le crée.
            user_data_dir = pathlib.Path('pwtest-user')
            user_data_dir.mkdir(parents=True, exist_ok=True)
            launch_args = [
                '--no-sandbox','--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars','--start-maximized',
                '--remote-debugging-port=9222',
                '--disable-background-timer-throttling',
                '--disable-renderer-backgrounding',
                '--disable-features=IsolateOrigins,site-per-process'
            ]
            # Contexte persistant (cookies, localStorage) entre runs
            try:
                browser_ctx = p.chromium.launch_persistent_context(
                    user_data_dir=str(user_data_dir),
                    headless=headless,
                    args=launch_args,
                    locale='fr-FR',
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                    viewport={'width': 1366, 'height': 900},
                )
            except Exception as e_launch:
                msg = str(e_launch)
                if 'ProcessSingleton' in msg or 'profile is already in use' in msg or 'SingletonLock' in msg:
                    # Profil verrouillé -> fallback direct minimal (headful si possible)
                    try:
                        return _scrape_leclerc_minimal(url, debug=debug, headful=not headless)
                    except Exception:
                        return {"ok": False, "used_playwright": True, "error": f"profile_lock_and_minimal_failed: {e_launch}"}
                return {"ok": False, "used_playwright": True, "error": f"launch_error: {e_launch}"}
            ctx = browser_ctx  # compatibilité noms
            ctx.set_extra_http_headers({
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.6,en;q=0.5',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'Upgrade-Insecure-Requests': '1',
                'Accept-Encoding': 'gzip, deflate, br',
                'Sec-CH-UA': '"Chromium";v="124", "Not.A/Brand";v="24", "Google Chrome";v="124"',
                'Sec-CH-UA-Mobile': '?0',
                'Sec-CH-UA-Platform': '"macOS"'
            })
            pages = ctx.pages
            page = pages[0] if pages else ctx.new_page()
            # Anti webdriver flag simple
            try:
                page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
                page.add_init_script("window.chrome = {runtime:{}};")
                page.add_init_script("Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3]});Object.defineProperty(navigator,'languages',{get:()=>['fr-FR','fr']});")
            except Exception:
                pass
            # Phase 1: homepage (obtenir cookies)
            try:
                r1 = page.goto('https://www.leclercdrive.fr/', timeout=25000, wait_until='domcontentloaded')
                page.wait_for_timeout(1200)
                # Scroll / mouvement souris pour paraître humain
                try:
                    page.mouse.move(200,200, steps=8)
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight/3)")
                except Exception:
                    pass
                attempts.append({'step':'home','status': r1.status if r1 else None})
            except Exception as _e:
                attempts.append({'step':'home','error': str(_e)[:120]})
            # Si challenge sur homepage, attendre un peu et reloader
            for i in range(3):
                chtml = (page.content() or '').lower()
                if 'captcha-delivery.com' in chtml or 'please enable javascript' in chtml:
                    attempts.append({'step':'home_challenge','retry': i+1})
                    page.wait_for_timeout(1800 + i*600)
                    try:
                        page.reload(wait_until='domcontentloaded', timeout=20000)
                        page.wait_for_timeout(800)
                    except Exception:
                        break
                else:
                    break
            # Phase 2: produit
            product_status = None
            try:
                r2 = page.goto(url, timeout=35000, wait_until='domcontentloaded')
                product_status = r2.status if r2 else None
                # Attendre activité réseau initiale terminée
                try:
                    page.wait_for_load_state('networkidle', timeout=15000)
                except Exception:
                    pass
                # Petites pauses aléatoires + reload si challenge persiste
                for cycle in range(5):
                    phtml_low = (page.content() or '').lower()
                    if 'captcha-delivery.com' not in phtml_low and 'please enable javascript' not in phtml_low and '403' not in phtml_low:
                        break
                    attempts.append({'step':'product_challenge','cycle': cycle+1})
                    # Mouvement + scroll partiel avant reload
                    try:
                        page.mouse.move(300+cycle*15, 300+cycle*10, steps=5)
                        page.evaluate("window.scrollTo(0, (document.body.scrollHeight/4)+%d)" % (cycle*150))
                    except Exception:
                        pass
                    page.wait_for_timeout(1600 + cycle*800)
                    try:
                        page.reload(wait_until='domcontentloaded', timeout=25000)
                        page.wait_for_timeout(700)
                    except Exception:
                        break
                # Dernière tentative: si toujours challenge mais cookie datadome existe, refaire un goto produit
                try:
                    cookies = {c['name']: c['value'] for c in ctx.cookies()}
                    if 'datadome' in cookies and 'captcha-delivery.com' in (page.content() or '').lower():
                        attempts.append({'step':'datadome_retry'})
                        page.wait_for_timeout(1200)
                        page.goto(url, timeout=30000, wait_until='domcontentloaded')
                        page.wait_for_timeout(1500)
                except Exception:
                    pass
                # Une fois (potentiellement) résolu, extraire HTML
                html = page.content() or ''
                attempts.append({'step':'product','status': product_status, 'len': len(html)})
            except Exception as _e:
                attempts.append({'step':'product','error': str(_e)[:160]})
            # Sauvegarder l'état (cookies) pour prochains appels
            try:
                # On sauvegarde juste un snapshot d'état cookies pour debug; le contexte persistant user_data_dir garde déjà tout
                ctx.storage_state(path=str(state_file))
            except Exception:
                pass
            try:
                ctx.close(); browser_ctx.close()
            except Exception:
                pass
        low = (html or '').lower()
        if ('captcha-delivery.com' in low or 'please enable javascript' in low or (len(html) < 800 and '403' in low)):
            # Si mode headful demandé, laisser une fenêtre de temps pour résolution manuelle du challenge
            if headful_env:
                try:
                    # Pause interactive (jusqu'à 15s) pour que l'utilisateur résolve éventuellement un captcha visible.
                    for wait_slot in range(15):
                        ph = (page.content() or '').lower()
                        if 'captcha-delivery.com' not in ph and 'please enable javascript' not in ph and '403' not in ph:
                            html = page.content() or ''
                            low = html.lower()
                            attempts.append({'step': 'manual_solve_wait', 'seconds': wait_slot})
                            break
                        page.wait_for_timeout(1000)
                    # Re-check après éventuelle résolution
                    if 'captcha-delivery.com' in low or 'please enable javascript' in low or (len(html) < 800 and '403' in low):
                        return {"ok": False, "bot_protection": True, "used_playwright": True, "attempts": attempts, "reason": "challenge_persist_after_headless"}
                except Exception:
                    return {"ok": False, "bot_protection": True, "used_playwright": True, "attempts": attempts, "reason": "challenge_persist_after_headless"}
            else:
                return {"ok": False, "bot_protection": True, "used_playwright": True, "attempts": attempts, "reason": "challenge_persist_after_headless"}
        # Réutiliser logique simplifiée d’extraction prix/EAN déjà codée (copie partielle)
        price = None
        for m in _re.finditer(r'"(priceInCents|sellingPriceInCents|sellingPrice)"\s*:\s*(\d{2,7})', html):
            try:
                val = int(m.group(2));
                if 10 <= val <= 200000:
                    price = round(val/100.0, 2); break
            except Exception: pass
        if price is None:
            m = _re.search(r'"nrPVUnitaireTTC"\s*:\s*([0-9]+(?:\.[0-9]{1,2})?)', html)
            if m:
                try:
                    v = float(m.group(1))
                    if 0.1 < v < 500:
                        price = round(v, 2)
                except Exception:
                    pass
        if price is None:
            m = _re.search(r'"price"\s*:\s*"?([0-9]+,[0-9]{2})"?', html)
            if m:
                try: price = float(m.group(1).replace(',', '.'))
                except Exception: pass
        if price is None:
            m = _re.search(r'([0-9]+,[0-9]{2})\s*€', html)
            if m:
                try: price = float(m.group(1).replace(',', '.'))
                except Exception: pass
        desc = ''
        for pat in [
            r'<h1[^>]*class="[^"]*(?:titre|title|product-name)[^"]*"[^>]*>(.*?)</h1>',
            r'<h1[^>]*>(.*?)</h1>',
            r'<title>(.*?)</title>',
            r'<meta name="description" content="([^"]+)"'
        ]:
            mm = _re.search(pat, html, _re.S)
            if mm:
                raw = mm.group(1)
                desc = _re.sub('<[^<]+?>',' ', raw)
                desc = _re.sub(r'\s+',' ', desc).strip()
                break
        ean = extract_ean_generic(html) or None
        if ean is None:
            m = _re.search(r'"sCodeEAN"\s*:\s*"(\d{8,14})"', html)
            if m:
                ean = m.group(1)
        # Description enrichie via sLibelleLigne1/2 si nécessaire
        if (not desc or len(desc) < 5):
            m1 = _re.search(r'"sLibelleLigne1"\s*:\s*"([^"]{3,120})"', html)
            if m1:
                part1 = m1.group(1)
                m2 = _re.search(r'"sLibelleLigne2"\s*:\s*"([^"]{3,160})"', html)
                if m2:
                    desc = (part1 + ' ' + m2.group(1)).strip()
                else:
                    desc = part1.strip()
    except Exception as e:
        return {"ok": False, "source": "leclerc", "error": f"leclerc scrape error: {e}"}
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
    try:
        from .stores import carrefour as _carrefour_mod  # type: ignore
        return _carrefour_mod.search_by_ean(ean, store_slug=store_slug, product_url=product_url, store_url=store_url, debug=debug)
    except Exception as e:
        return {'ok': False, 'error': f'carrefour_module_missing:{e}'}

def _carrefour_playwright_minimal(ean: str, prefound_url: str = None, headful: bool = False, debug: bool = False, store_slug: str = None):
    try:
        from .stores import carrefour as _carrefour_mod  # type: ignore
        return _carrefour_mod.playwright_fallback(ean, store_slug=store_slug, product_url=prefound_url, headful=headful, debug=debug)
    except Exception as e:
        return {'ok': False, 'error': f'carrefour_module_missing:{e}'}

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
        from .stores import intermarche as _im
        return _im.playwright_fallback(ean, headful=headful, debug=debug, prefound_url=prefound_url)
    except Exception as e:
        return {'ok': False, 'error': f'im_module_missing:{e}'}

def _search_intermarche_by_ean(ean: str, debug: bool = False):
    """Wrapper rétrocompatible pointant vers stores.intermarche.search_by_ean."""
    try:
        from .stores import intermarche as _im
        return _im.search_by_ean(ean, debug=debug)
    except Exception as e:
        return {'ok': False, 'error': f'im_module_missing:{e}'}

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
    ean = (ean or '').strip()
    if not ean:
        return {"ok": False, "error": "missing ean"}
    wanted = [s.strip().lower() for s in stores] if stores else None
    urls_map = _PRODUCT_URLS.get(ean)

    # Produit canonique (si Carrefour accessible) utilisé plus bas
    canonical_product = None
    try:
        from .productinfo import canonical as _canonical_mod  # type: ignore
        canonical_product = _canonical_mod.get_canonical_product(ean)
    except Exception:
        canonical_product = None

    results: list[dict] = []

    if not urls_map:
        # Mode fallback dynamique sans mapping: on tente carrefour + intermarche (+ auchan si possible par EAN)
        if wanted is None or 'carrefour' in wanted:
            try:
                from .stores import carrefour as _carrefour_mod
                car = _carrefour_mod.search_by_ean(ean, store_slug=carrefour_store, product_url=carrefour_product, store_url=carrefour_store_url, debug=debug)
            except Exception:
                car = _search_carrefour_by_ean(ean, store_slug=carrefour_store, product_url=carrefour_product, store_url=carrefour_store_url, debug=debug)
            if car.get('ok'):
                results.append({
                    'store': 'carrefour', 'ok': True, 'price': car.get('price'), 'ean': car.get('ean'), 'desc': car.get('desc'), 'url': car.get('url'),
                    'store_slug': carrefour_store or car.get('store_slug'), 'product_forced': bool(carrefour_product), 'playwright': car.get('playwright'), 'price_source': car.get('price_source')
                })
            else:
                results.append({'store': 'carrefour', 'ok': False, 'error': car.get('error')})
        if wanted is None or 'intermarche' in wanted:
            try:
                from .stores import intermarche as _im_mod
                im = _im_mod.search_by_ean(ean, debug=debug)
            except Exception:
                im = _search_intermarche_by_ean(ean, debug=debug)
            if im.get('ok'):
                results.append({'store': 'intermarche', 'ok': True, 'price': im.get('price'), 'ean': im.get('ean'), 'desc': im.get('desc'), 'url': im.get('url')})
            else:
                results.append({'store': 'intermarche', 'ok': False, 'error': im.get('error')})
        if wanted is None or 'auchan' in wanted:
            try:
                au = _search_auchan_by_ean(ean, debug=debug)
            except Exception as e2:
                au = {'ok': False, 'error': f'auchan_exc:{e2}'}
            if au.get('ok'):
                results.append({'store': 'auchan', 'ok': True, 'price': au.get('price'), 'ean': ean, 'desc': au.get('desc'), 'url': au.get('url')})
            else:
                results.append({'store': 'auchan', 'ok': False, 'error': au.get('error')})
        out = {"ok": True, "ean": ean, "results": results, "note": "dynamic_fallback_no_mapping"}
        if canonical_product:
            out['product'] = canonical_product
        return out

    # Leclerc via mapping (URL directe)
    if ('leclerc' in urls_map) and (wanted is None or 'leclerc' in wanted):
        url = urls_map['leclerc']
        try:
            try:
                from .stores import leclerc as _leclerc_mod
                lr = _leclerc_mod.scrape_minimal(url, debug=False, headful=True)
            except Exception:
                lr = _scrape_leclerc_minimal(url, debug=False, headful=True)
            results.append({
                'store': 'leclerc', 'ok': lr.get('ok'), 'price': lr.get('price'), 'ean': lr.get('ean'), 'desc': lr.get('desc'), 'url': url, 'bot': lr.get('bot_protection', False)
            })
        except Exception as e:
            results.append({'store': 'leclerc', 'ok': False, 'error': str(e)})

    # Carrefour (multi-slug possible)
    if (wanted is None or 'carrefour' in wanted):
        multi_slugs: list[str] = []
        if carrefour_store and ',' in carrefour_store:
            multi_slugs = [s.strip() for s in carrefour_store.split(',') if s.strip()]
        if multi_slugs:
            for slug in multi_slugs:
                try:
                    from .stores import carrefour as _carrefour_mod
                    car = _carrefour_mod.search_by_ean(ean, store_slug=slug, product_url=carrefour_product, store_url=carrefour_store_url, debug=debug)
                except Exception:
                    car = _search_carrefour_by_ean(ean, store_slug=slug, product_url=carrefour_product, store_url=carrefour_store_url, debug=debug)
                short = ''
                try:
                    parts = slug.split('-')
                    if len(parts) >= 2:
                        short = parts[1].lower()
                except Exception:
                    pass
                label = f'carrefour_{short}' if short else f'carrefour_{slug}'
                if car.get('ok'):
                    results.append({
                        'store': label, 'ok': True, 'price': car.get('price'), 'ean': car.get('ean'), 'desc': car.get('desc'), 'url': car.get('url'), 'store_slug': slug,
                        'product_forced': bool(carrefour_product), 'playwright': car.get('playwright'), 'price_source': car.get('price_source'), 'multi': True
                    })
                else:
                    results.append({'store': label, 'ok': False, 'error': car.get('error'), 'store_slug': slug, 'multi': True})
        else:
            try:
                from .stores import carrefour as _carrefour_mod
                car = _carrefour_mod.search_by_ean(ean, store_slug=carrefour_store, product_url=carrefour_product, store_url=carrefour_store_url, debug=debug)
            except Exception:
                car = _search_carrefour_by_ean(ean, store_slug=carrefour_store, product_url=carrefour_product, store_url=carrefour_store_url, debug=debug)
            if car.get('ok'):
                results.append({
                    'store': 'carrefour', 'ok': True, 'price': car.get('price'), 'ean': car.get('ean'), 'desc': car.get('desc'), 'url': car.get('url'),
                    'store_slug': carrefour_store or car.get('store_slug'), 'product_forced': bool(carrefour_product), 'playwright': car.get('playwright'), 'price_source': car.get('price_source')
                })
            else:
                results.append({'store': 'carrefour', 'ok': False, 'error': car.get('error')})

    # Intermarché
    if (wanted is None or 'intermarche' in wanted):
        try:
            from .stores import intermarche as _im_mod
            im = _im_mod.search_by_ean(ean, debug=debug)
        except Exception:
            im = _search_intermarche_by_ean(ean, debug=debug)
        if im.get('ok'):
            results.append({'store': 'intermarche', 'ok': True, 'price': im.get('price'), 'ean': im.get('ean'), 'desc': im.get('desc'), 'url': im.get('url')})
        else:
            results.append({'store': 'intermarche', 'ok': False, 'error': im.get('error')})

    # Auchan (best-effort HTTP simple pour l'instant)
    if (wanted is None or 'auchan' in wanted):
        try:
            au = _search_auchan_by_ean(ean, debug=debug)
        except Exception as e2:
            au = {'ok': False, 'error': f'auchan_exc:{e2}'}
        if au.get('ok'):
            results.append({'store': 'auchan', 'ok': True, 'price': au.get('price'), 'ean': ean, 'desc': au.get('desc'), 'url': au.get('url')})
        else:
            results.append({'store': 'auchan', 'ok': False, 'error': au.get('error')})

    out = {"ok": True, "ean": ean, "results": results}
    if canonical_product:
        out['product'] = canonical_product
    return out

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
            code, final, html=_simple(search_url)
        except urllib.error.HTTPError as he:
            if he.code in (403,429):
                return {'ok': False, 'error': 'blocked_auchan_http', 'code': he.code}
            return {'ok': False, 'error': f'http_{he.code}'}
        if code!=200 or not html:
            return {'ok': False, 'error': 'empty_search_auchan'}
        if ean not in html:
            return {'ok': False, 'error': 'ean_not_in_search'}
        m=_re.search(r'href="(https://www\.auchan\.fr/[^"]*produit[^"]*)"', html)
        if not m:
            m=_re.search(r'href="(/[^"?#]*produit[^"?#]*)"', html)
            if m:
                prod_url='https://www.auchan.fr'+m.group(1)
            else:
                return {'ok': False, 'error': 'no_product_link'}
        else:
            prod_url=m.group(1)
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

def _carrefour_playwright_minimal(ean: str, prefound_url: str = None, headful: bool = False, debug: bool = False, store_slug: str = None):
    """Recherche + extraction produit Carrefour via Playwright (fallback)."""
    try:
        from playwright.sync_api import sync_playwright as _pw
    except Exception:
        return {'ok': False, 'error': 'playwright_not_available'}
    import re, pathlib, datetime, os, json as _json
    _KW_MAP = {
        '8700216648783': 'lessive capsules ariel pods original',
    }
    user_data_dir = pathlib.Path('pw-carrefour')
    user_data_dir.mkdir(parents=True, exist_ok=True)
    with _pw() as p:
        ctx = None
        page = None
        fallback_used = False
        # --- Instrumentation réseau (activée si debug) ---
        network_logs = {
            'requests': [],  # {ts,url,method,postDataSnippet}
            'responses': []  # {ts,url,status,ct,bodySnippet}
        }
        keywords = ['graphql', 'price', '/p/', 'product']
        try:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=not headful,
                args=['--no-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled'],
                locale='fr-FR',
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
                viewport={'width':1280,'height':900}
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
        except Exception as e:
            # Fallback: profil verrouillé (ProcessSingleton) ou autre → on bascule en contexte éphémère
            fallback_used = True
            try:
                browser = p.chromium.launch(headless=not headful, args=['--no-sandbox','--disable-dev-shm-usage','--disable-blink-features=AutomationControlled'])
                ctx = browser.new_context(
                    locale='fr-FR',
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
                    viewport={'width':1280,'height':900}
                )
                page = ctx.new_page()
            except Exception as ee:
                return {'ok': False, 'error': f'playwright_launch_fail:{ee}'}
        try:
            page.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        except Exception:
            pass
        # Handlers réseau (seulement si debug pour ne pas alourdir exécution normale)
        if debug:
            try:
                def _match(u: str):
                    lu = u.lower()
                    return any(k in lu for k in keywords)
                def _now():
                    return datetime.datetime.utcnow().isoformat()
                page.on('request', lambda req: (
                    network_logs['requests'].append({
                        'ts': _now(),
                        'url': req.url,
                        'method': req.method,
                            'postDataSnippet': ( (req.post_data() if callable(getattr(req,'post_data',None)) else (req.post_data if hasattr(req,'post_data') else '')) or '' )[:300]
                    }) if _match(req.url) else None
                ))
                def _on_response(res):
                    try:
                        url = res.url
                        if not _match(url):
                            return
                        status = res.status
                        ct = res.headers.get('content-type','')
                        body_snip = ''
                        if 'application/json' in ct.lower():
                            try:
                                txt = res.text()
                                if txt:
                                    body_snip = txt[:1000]
                            except Exception:
                                pass
                        network_logs['responses'].append({
                            'ts': _now(),
                            'url': url,
                            'status': status,
                            'ct': ct[:80],
                            'bodySnippet': body_snip
                        })
                    except Exception:
                        pass
                page.on('response', _on_response)
            except Exception:
                pass
        html_search = ''
        target_url = prefound_url
        html_prod = ''
        already_product = False
        # Si un magasin spécifique est demandé, tenter d'abord de charger sa page pour setter les cookies de contexte
        store_id_forced = None
        try:
            if store_slug:
                try:
                    store_url = f"https://www.carrefour.fr/magasin/{store_slug.strip().strip('/')}"
                    page.goto(store_url, timeout=30000, wait_until='domcontentloaded')
                    page.wait_for_timeout(1800)
                    # Cookies consent éventuels avant clic magasin
                    for sel in ["button:has-text('Accepter')", "button:has-text('Tout accepter')", "#onetrust-accept-btn-handler"]:
                        try:
                            btn = page.locator(sel)
                            if btn and btn.count()>0:
                                btn.first.click(timeout=2200)
                                page.wait_for_timeout(700)
                                break
                        except Exception:
                            pass
                    # Essayer de cliquer sur un bouton de sélection du magasin (si présent)
                    clicked_store=False
                    for sel in ["button:has-text('Choisir ce magasin')", "button:has-text('Ce magasin')", "button:has-text('Mon magasin')", "[data-testid*='choose-store'] button", "[data-testid*='select-store']"]:
                        try:
                            btn = page.locator(sel)
                            if btn and btn.count()>0:
                                btn.first.click(timeout=3000)
                                page.wait_for_timeout(1500)
                                clicked_store=True
                                break
                        except Exception:
                            pass
                    # Essayer d'extraire un éventuel storeId dans les scripts (window.__NEXT_DATA__ ou JSON initial)
                    try:
                        js_store = page.evaluate("(() => {const s=[...document.querySelectorAll('script')].map(x=>x.textContent||'').join('\n'); const m=s.match(/storeId\"?\s*[:=]\s*\"([0-9A-Za-z-]+)\"/); return m?m[1]:null;})()")
                        if js_store:
                            store_id_forced = js_store
                    except Exception:
                        pass
                    # Si pas trouvé, inspecter localStorage
                    if not store_id_forced:
                        try:
                            ls_store = page.evaluate("(() => {for (const [k,v] of Object.entries(localStorage)){ if(/store.?id/i.test(k) && typeof v==='string' && v.length<80) return v;} return null;})()")
                            if ls_store:
                                store_id_forced = ls_store
                        except Exception:
                            pass
                    if store_id_forced:
                        # Injecter variable locale/localStorage + cookie storeId
                        try: page.evaluate(f"localStorage.setItem('storeId','{store_id_forced}');")
                        except Exception: pass
                        try: ctx.add_cookies([{ 'name':'storeId', 'value': str(store_id_forced), 'domain':'.carrefour.fr', 'path':'/' }])
                        except Exception: pass
                    if debug:
                        try:
                            dbg_dir = pathlib.Path(__file__).parent/'debug'; dbg_dir.mkdir(exist_ok=True)
                            import datetime as _dt
                            ts=_dt.datetime.utcnow().strftime('%Y%m%d-%H%M%S')
                            (dbg_dir/f'carrefour-store-{store_slug}-{"ok" if clicked_store else "raw"}-{ts}.html').write_text((page.content() or '')[:250000], encoding='utf-8', errors='ignore')
                            # Collecte cookies + localStorage pour inspection ultérieure
                            store_meta = {}
                            try:
                                # cookies du contexte
                                ck = ctx.cookies()
                                store_meta['cookies'] = [c for c in ck if 'carrefour' in c.get('domain','') or 'carrefour' in c.get('name','').lower()]
                            except Exception:
                                pass
                            try:
                                ls = page.evaluate('Object.fromEntries(Object.entries(localStorage))')
                                if isinstance(ls, dict):
                                    filt = {k:v for k,v in ls.items() if any(x in k.lower() for x in ['store','mag','magasin','enseigne'])}
                                    store_meta['localStorage'] = filt
                            except Exception:
                                pass
                            try:
                                if store_id_forced:
                                    store_meta['store_id_forced'] = store_id_forced
                                (dbg_dir/f'carrefour-store-meta-{store_slug}-{ts}.json').write_text(__import__('json').dumps(store_meta, ensure_ascii=False, indent=2), encoding='utf-8')
                            except Exception:
                                pass
                        except Exception:
                            pass
                except Exception:
                    pass
                # Si toujours pas de store_id_forced tenter __NEXT_DATA__ léger (hors debug pour influence prix)
                if not store_id_forced:
                    try:
                        node = page.locator('#__NEXT_DATA__')
                        if node and node.count()>0:
                            raw = node.first.inner_text(timeout=1200)
                            import json as _json
                            try:
                                jd=_json.loads(raw)
                                def _s(o):
                                    if isinstance(o, dict):
                                        if 'storeId' in o and isinstance(o['storeId'], (str,int)):
                                            return str(o['storeId'])
                                        for v in o.values():
                                            r=_s(v)
                                            if r: return r
                                    elif isinstance(o, list):
                                        for v in o:
                                            r=_s(v)
                                            if r: return r
                                    return None
                                sid=_s(jd)
                                if sid:
                                    store_id_forced=sid
                                    try: page.evaluate(f"localStorage.setItem('storeId','{sid}');")
                                    except Exception: pass
                            except Exception:
                                pass
                    except Exception:
                        pass
            page.goto(f"https://www.carrefour.fr/s?q={ean}", timeout=35000, wait_until='domcontentloaded')
            page.wait_for_timeout(2000)
            # Cookies
            for sel in ["button:has-text('Accepter')", "button:has-text('Tout accepter')", "#onetrust-accept-btn-handler"]:
                try:
                    btn = page.locator(sel)
                    if btn and btn.count() > 0:
                        btn.first.click(timeout=2000)
                        page.wait_for_timeout(600)
                        break
                except Exception:
                    pass
            cur_url = ''
            try:
                cur_url = page.url or ''
            except Exception:
                pass
            for _ in range(5):
                try:
                    page.evaluate('window.scrollBy(0, document.body.scrollHeight/5)')
                except Exception:
                    pass
                page.wait_for_timeout(600)
            html_search = page.content() or ''
            if '/p/' in cur_url:
                already_product = True
                target_url = cur_url
                html_prod = html_search
            did_store_reload = False
        except Exception:
            did_store_reload = False
        if not already_product and not target_url:
            links = []
            try:
                hrefs = page.evaluate("""Array.from(document.querySelectorAll('a[href*="/p/"]')).map(a=>a.href)""")
                if isinstance(hrefs, list):
                    for u in hrefs:
                        if isinstance(u, str) and '/p/' in u and u.startswith('http') and u not in links:
                            links.append(u)
            except Exception:
                pass
            for m in re.finditer(r'href="(https://www\.carrefour\.fr/p/[^"?#]+)"', html_search):
                u = m.group(1)
                if u not in links:
                    links.append(u)
            if not links:
                next_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html_search, re.S)
                if next_match:
                    import json as _json
                    try:
                        data = _json.loads(next_match.group(1))
                        stack=[data]
                        seen=set()
                        while stack:
                            cur=stack.pop()
                            if isinstance(cur, dict):
                                for v in cur.values(): stack.append(v)
                            elif isinstance(cur, list):
                                for v in cur: stack.append(v)
                            elif isinstance(cur, str):
                                if 'https://www.carrefour.fr/p/' in cur and cur not in seen:
                                    seen.add(cur)
                        for u in seen:
                            if '/p/' in u and u.startswith('http') and u not in links:
                                links.append(u)
                    except Exception:
                        pass
            for pref in ['ariel','pods']:
                cand = next((u for u in links if pref in u.lower()), None)
                if cand:
                    target_url = cand; break
            if not target_url and links:
                target_url = links[0]
            if not target_url and ean in _KW_MAP:
                kw = _KW_MAP[ean]
                try:
                    page.goto(f"https://www.carrefour.fr/s?q={kw.replace(' ', '+')}", timeout=30000, wait_until='domcontentloaded')
                    page.wait_for_timeout(1800)
                    html_search2 = page.content() or ''
                    links2 = []
                    for m in re.finditer(r'href="(https://www\.carrefour\.fr/p/[^"?#]+)"', html_search2):
                        u = m.group(1)
                        if u not in links2:
                            links2.append(u)
                    for pref in ['ariel','pods']:
                        cand = next((u for u in links2 if pref in u.lower()), None)
                        if cand:
                            target_url = cand; break
                    if not target_url and links2:
                        target_url = links2[0]
                except Exception:
                    pass
        if not target_url:
            if debug:
                try:
                    dbg_dir = pathlib.Path(__file__).parent/'debug'; dbg_dir.mkdir(exist_ok=True)
                    import datetime as _dt
                    ts=_dt.datetime.utcnow().strftime('%Y%m%d-%H%M%S')
                    (dbg_dir/f'carrefour-search-fail-{ts}.html').write_text(html_search[:300000], encoding='utf-8', errors='ignore')
                except Exception:
                    pass
            try: ctx.close()
            except Exception: pass
            return {'ok': False, 'error': 'no_product_link_playwright'}
        if not already_product:
            try:
                page.goto(target_url, timeout=35000, wait_until='domcontentloaded')
                page.wait_for_timeout(2500)
                html_prod = page.content() or ''
                if store_slug and store_id_forced and not did_store_reload:
                    # Tentative reload pour recalcul prix magasin
                    did_store_reload = True
                    try:
                        page.wait_for_timeout(1200)
                        page.reload(wait_until='domcontentloaded')
                        page.wait_for_timeout(1600)
                        html_prod = page.content() or ''
                    except Exception:
                        pass
            except Exception as e:
                try: ctx.close()
                except Exception: pass
                return {'ok': False, 'error': f'goto_prod_fail:{e}'}
        low = (html_prod or '').lower()
        if ean not in low:
            try:
                page.evaluate('window.scrollTo(0, document.body.scrollHeight/2)')
                page.wait_for_timeout(1200)
                html_prod = page.content() or ''
                low = html_prod.lower()
            except Exception:
                pass
        def _extract_price(txt: str):
            patterns = [
                r'"price"\s*:\s*"?([0-9]+(?:[\.,][0-9]{1,2}))"?',
                r'"sellingPrice"\s*:\s*"?([0-9]+(?:[\.,][0-9]{1,2}))"?',
                r'"currentPrice"\s*:\s*"?([0-9]+(?:[\.,][0-9]{1,2}))"?',
                r'"value"\s*:\s*"?([0-9]+(?:[\.,][0-9]{1,2}))"?',
                r'content="([0-9]+(?:\.[0-9]{1,2}))"\s+itemprop="price"',
                r'([0-9]+,[0-9]{2})\s*€'
            ]
            for rg in patterns:
                m = re.search(rg, txt)
                if m:
                    raw = m.group(1).replace(',', '.')
                    try:
                        val = float(raw)
                        if 0.05 < val < 1000:
                            return round(val,2)
                    except Exception:
                        pass
            return None
        price = _extract_price(html_prod)
        price_source = 'html' if price is not None else None
        # Tentative: extraire prix de l'API recommandations (paramètre price=995) dans logs réseau
        try:
            if (price is None or price == 9.95) and 'network_logs' in locals():
                rec_best = None
                for req in network_logs.get('requests', []):
                    u = req.get('url') or ''
                    if '/api/recommendations' in u and 'product_cdbase='+ean in u:
                        # Chercher price=XXX
                        m = re.search(r'[?&]price=([0-9]{2,6})', u)
                        if m:
                            rawp = m.group(1)
                            try:
                                iv = int(rawp)
                                # Heuristique: 995 => 9.95 ; 1234 => 12.34 ; si >= 100 et <= 999999
                                if 50 <= iv <= 500000:
                                    pv = round(iv/100.0, 2)
                                    rec_best = pv
                            except Exception:
                                pass
                if rec_best is not None:
                    # Si différent, on privilégie la valeur réseau comme potentiellement magasin/référentiel
                    if price is None or rec_best != price:
                        price = rec_best
                        price_source = 'network_recommendations_param'
                    elif price_source is None:
                        price_source = 'network_recommendations_param'
            # Si toujours rien, tenter extraits JSON tronqués des responses
            if price is None and 'network_logs' in locals():
                for resp in network_logs.get('responses', []):
                    urlr = (resp.get('url') or '').lower()
                    if any(k in urlr for k in ['recommend','price','product']):
                        body_snip = resp.get('bodySnippet') or ''
                        m2 = re.search(r'"price"\s*:\s*([0-9]+(?:\.[0-9]{1,2})?)', body_snip)
                        if m2:
                            try:
                                vv = float(m2.group(1))
                                if 0.05 < vv < 1000:
                                    price = round(vv,2)
                                    price_source = 'network_body_snippet'
                                    break
                            except Exception:
                                pass
        except Exception:
            pass
        desc = ''
        mt = re.search(r'<title>([^<]{5,160})</title>', html_prod)
        if mt:
            import re as _re
            desc = _re.sub(r'\s+',' ', mt.group(1)).strip()
        ean_found = None
        if ean and ean in low:
            ean_found = ean
        if not ean_found:
            for rg in [r'"gtin13"\s*:\s*"(\d{13})"', r'"gtin"\s*:\s*"(\d{13})"', r'"ean"\s*:\s*"(\d{13})"', r'"codeEan"\s*:\s*"(\d{13})"']:
                m = re.search(rg, html_prod)
                if m:
                    ean_found = m.group(1); break
        if not ean_found:
            m = re.search(r'\b\d{13}\b', html_prod)
            if m:
                ean_found = m.group(0)
        out = {'ok': True, 'url': target_url, 'price': price, 'ean': ean_found, 'desc': desc, 'playwright': True, 'store_slug': store_slug, 'fallback_ctx': fallback_used}
        if price_source:
            out['price_source'] = price_source
        try:
            if 'store_id_forced' in locals() and store_id_forced:
                out['store_id_forced'] = store_id_forced
        except Exception:
            pass
        if debug and store_slug:
            # Essayer de renvoyer un petit aperçu contexte magasin (sans tout exposer)
            try:
                ls_small = {}
                try:
                    ls_all = page.evaluate('Object.fromEntries(Object.entries(localStorage))')
                    if isinstance(ls_all, dict):
                        for k,v in ls_all.items():
                            if any(x in k.lower() for x in ['store','mag','magasin']):
                                ls_small[k]=v
                except Exception: pass
                ck_small = []
                try:
                    ck_all = ctx.cookies()
                    for c in ck_all:
                        n=c.get('name','').lower()
                        if any(x in n for x in ['store','mag','magasin']):
                            ck_small.append({'name':c.get('name'), 'value':c.get('value')[:60], 'domain':c.get('domain')})
                except Exception: pass
                out['store_context_debug']={'localStorage':ls_small,'cookies':ck_small}
            except Exception:
                pass
        if debug and (price is None or ean_found is None):
            try:
                dbg_dir = pathlib.Path(__file__).parent/'debug'; dbg_dir.mkdir(exist_ok=True)
                ts = datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')
                (dbg_dir/f'carrefour-product-miss-{ts}.html').write_text(html_prod[:200000], encoding='utf-8', errors='ignore')
            except Exception:
                pass
        if debug:
            try:
                dbg_dir = pathlib.Path(__file__).parent/'debug'; dbg_dir.mkdir(exist_ok=True)
                ts = datetime.datetime.utcnow().strftime('%Y%m%d-%H%M%S')
                (dbg_dir/f'carrefour-minimal-{ts}.html').write_text(html_prod[:200000], encoding='utf-8', errors='ignore')
                # Sauvegarde logs réseau si collectés
                if network_logs['requests'] or network_logs['responses']:
                    # Réduction : ne garder que 120 entrées de chaque pour limiter taille
                    if len(network_logs['requests'])>120:
                        network_logs['requests'] = network_logs['requests'][-120:]
                    if len(network_logs['responses'])>120:
                        network_logs['responses'] = network_logs['responses'][-120:]
                    (dbg_dir/f'carrefour-network-{ts}.json').write_text(_json.dumps(network_logs, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception: pass
        # Pause optionnelle pour permettre ouverture manuelle DevTools avant fermeture
        try:
            pause_env = int(os.getenv('CARREFOUR_DEBUG_PAUSE','0'))
        except Exception:
            pause_env = 0
        if debug and headful and pause_env>0:
            # Limiter la pause à 10 minutes pour éviter blocage oubliée
            capped = min(pause_env, 600)
            try:
                page.wait_for_timeout(capped*1000)
            except Exception:
                pass
        try:
            ctx.close()
        except Exception:
            pass
        return out

        au = _search_auchan_by_ean(ean, debug=debug)
        if au.get('ok'):
            results.append({
                'store': 'auchan',
                'ok': True,
                'price': au.get('price'),
                'ean': au.get('ean'),
                'desc': au.get('desc'),
                'url': au.get('url')
            })
        else:
            results.append({'store': 'auchan', 'ok': False, 'error': au.get('error')})
    # Placeholders autres enseignes pour étapes suivantes
    if wanted:
        existing = {r['store'] for r in results}
        for s in wanted:
            if s in existing:
                continue
            if s not in urls_map and s != 'carrefour':  # carrefour déjà tenté dynamiquement
                results.append({'store': s, 'ok': False, 'error': 'non_implemente'})
    else:
        # Ajouter indicateurs TODO pour visibilité
        for s in ('carrefour','auchan','intermarche','systeme-u','lidl','aldi'):
            if s in urls_map:
                continue
            results.append({'store': s, 'ok': False, 'error': 'todo'})
    # Cache dynamique (ajoute les URLs découvertes pour accélérer prochains appels)
    try:
        _ensure_dynamic_store_mapping(ean, results)
    except Exception:
        pass
    return {"ok": True, "ean": ean, "results": results}

PW_OK = False
SEL_OK = False
def sync_playwright():
    class Dummy:
        def __enter__(self): return self
        def __exit__(self, exc_type, exc_val, exc_tb): pass
        def chromium(self): return self
        def launch(self, **kwargs): return self
        def new_page(self): return self
        def goto(self, url): pass
        def content(self): return ""
    return Dummy()

class uc:
    class ChromeOptions:
        def __init__(self): pass
    class Chrome:
        def __init__(self, options=None): pass
from urllib.parse import urlsplit, parse_qs
from http.cookiejar import CookieJar
from urllib.request import build_opener, HTTPCookieProcessor, Request
import gzip
import io
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import os
import json

# Handler HTTP principal pour l’API Maxicourses
class _Handler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, payload: dict):
        data = json.dumps(payload).encode('utf-8')
        try:
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass
        except Exception:
            try:
                self.close_connection = True
            except Exception:
                pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        try:
            path = self.path.split('?', 1)[0]
            if path == '/health':
                return self._send_json(200, {"ok": True})
            if path == '/scrape':
                qs = parse_qs(urlsplit(self.path).query)
                url = (qs.get('url') or [''])[0]
                attach = ((qs.get('attach') or ['0'])[0]).lower() in ('1','true','yes')
                nopuzzle = ((qs.get('nopuzzle') or ['1'])[0]).lower() in ('1','true','yes')
                if not url:
                    return self._send_json(400, {"ok": False, "error": "missing url"})
                debug_flag = ((qs.get('debug') or ['0'])[0]).lower() in ('1','true','yes','on')
                if 'leclercdrive.fr' in url:
                    force_minimal = ((qs.get('minimal') or ['0'])[0]).lower() in ('1','true','yes','on')
                    headful_flag = ((qs.get('headful') or ['0'])[0]).lower() in ('1','true','yes','on')
                    res = None
                    if force_minimal:
                        res = _scrape_leclerc_minimal(url, debug=debug_flag, headful=headful_flag or True)
                    if not res:
                        res = _scrape_direct_leclerc(url, debug_override=debug_flag)
                        if (not res.get('ok')) and res.get('bot_protection'):
                            res = _scrape_leclerc_headless(url, debug=debug_flag, headful_override=headful_flag)
                        if (not res.get('ok')) or res.get('price') in (None, 0) or not res.get('ean'):
                            res_min = _scrape_leclerc_minimal(url, debug=debug_flag, headful=headful_flag or True)
                            if res_min.get('ok') and res_min.get('price') and res_min.get('ean'):
                                res = res_min
                else:
                    res = _run_self(url, attach=attach, nopuzzle=nopuzzle)
                return self._send_json(200, res)
            if path == '/fetch':
                qs = parse_qs(urlsplit(self.path).query)
                url = (qs.get('url') or [''])[0].strip()
                referer = (qs.get('referer') or [''])[0].strip() or re.sub(r'^(https?://[^/]+/).*', r'\1', url)
                attach = ((qs.get('attach') or ['0'])[0]).lower() in ('1','true','yes')
                nopuzzle = ((qs.get('nopuzzle') or ['0'])[0]).lower() in ('1','true','yes')
                autoclick = ((qs.get('autoclick') or ['1'])[0]).lower() in ('1','true','yes')
                wait_puzzle = not nopuzzle
                if not url:
                    return self._send_json(400, {"ok": False, "error": "missing url"})
                res = {"ok": False, "code": None, "final_url": None, "html": "", "bot_protection": False}
                if attach:
                    try:
                        r = fetch_playwright_html(url, referer, wait_puzzle=wait_puzzle, autoclick=autoclick)
                        if isinstance(r, dict):
                            res.update(r)
                    except Exception:
                        pass
                if (not res.get("ok")) or (not res.get("html")):
                    code, final_url, html = fetch_raw_with_meta(url, referer)
                    res.update({
                        "ok": True,
                        "code": code,
                        "final_url": final_url,
                        "html": html,
                        "bot_protection": is_bot_protection(html) if isinstance(html, str) else False,
                    })
                return self._send_json(200, res)
            if path == '/carrefour_check':
                qs = parse_qs(urlsplit(self.path).query)
                raw = (qs.get('slugs') or [''])[0]
                if not raw:
                    return self._send_json(400, {"ok": False, "error": "missing slugs"})
                slugs = [s.strip() for s in raw.split(',') if s.strip()]
                res = _check_carrefour_slugs(slugs)
                return self._send_json(200, {"ok": True, "results": res})
            if path == '/compare':
                qs = parse_qs(urlsplit(self.path).query)
                ean = (qs.get('ean') or [''])[0].strip()
                attach = ((qs.get('attach') or ['1'])[0]).lower() in ('1','true','yes')
                nopuzzle = ((qs.get('nopuzzle') or ['1'])[0]).lower() in ('1','true','yes')
                debug_flag = ((qs.get('debug') or ['0'])[0]).lower() in ('1','true','yes','on')
                stores = (qs.get('stores') or [''])[0]
                stores = [s.strip() for s in stores.split(',')] if stores else None
                carrefour_store = (qs.get('carrefour_store') or [''])[0].strip() or None
                carrefour_product = (qs.get('carrefour_product') or [''])[0].strip() or None
                carrefour_store_url = (qs.get('carrefour_store_url') or [''])[0].strip() or None
                if not ean:
                    return self._send_json(400, {"ok": False, "error": "missing ean"})
                res = _compare_ean(ean, attach=attach, nopuzzle=nopuzzle, debug=debug_flag, stores=stores, carrefour_store=carrefour_store, carrefour_product=carrefour_product, carrefour_store_url=carrefour_store_url)
                return self._send_json(200, res)
            return self._send_json(404, {"ok": False, "error": "not found"})
        except Exception as e:
            return self._send_json(500, {"ok": False, "error": str(e)})

    def do_POST(self):
        try:
            path = self.path.split('?', 1)[0]
            n = int(self.headers.get('Content-Length') or '0')
            body = self.rfile.read(n) if n else b''
            try:
                payload = json.loads(body.decode('utf-8') or '{}')
            except Exception:
                payload = {}
            if path == '/scrape':
                url = (payload.get('url') or '').strip()
                attach = str(payload.get('attach') or '0').lower() in ('1','true','yes')
                nopuzzle = str(payload.get('nopuzzle') or '1').lower() in ('1','true','yes')
                debug_flag = str(payload.get('debug') or '0').lower() in ('1','true','yes','on')
                headful_flag = str(payload.get('headful') or '0').lower() in ('1','true','yes','on')
                if not url:
                    return self._send_json(400, {"ok": False, "error": "missing url"})
                if 'leclercdrive.fr' in url:
                    force_minimal = str(payload.get('minimal') or '0').lower() in ('1','true','yes','on')
                    res = None
                    if force_minimal:
                        res = _scrape_leclerc_minimal(url, debug=debug_flag, headful=True)
                    if not res:
                        res = _scrape_direct_leclerc(url, debug_override=debug_flag)
                        if (not res.get('ok')) and res.get('bot_protection'):
                            res = _scrape_leclerc_headless(url, debug=debug_flag, headful_override=headful_flag)
                        if (not res.get('ok')) or res.get('price') in (None,0) or not res.get('ean'):
                            res_min = _scrape_leclerc_minimal(url, debug=debug_flag, headful=True)
                            if res_min.get('ok') and res_min.get('price') and res_min.get('ean'):
                                res = res_min
                else:
                    res = _run_self(url, attach=attach, nopuzzle=nopuzzle)
                return self._send_json(200, res)
            if path == '/fetch':
                url = (payload.get('url') or '').strip()
                referer = (payload.get('referer') or '').strip() or re.sub(r'^(https?://[^/]+/).*', r'\1', url)
                attach = str(payload.get('attach') or '0').lower() in ('1','true','yes')
                nopuzzle = str(payload.get('nopuzzle') or '0').lower() in ('1','true','yes')
                autoclick = str(payload.get('autoclick') or '1').lower() in ('1','true','yes')
                wait_puzzle = not nopuzzle
                if not url:
                    return self._send_json(400, {"ok": False, "error": "missing url"})
                res = {"ok": False, "code": None, "final_url": None, "html": "", "bot_protection": False}
                if attach:
                    try:
                        r = fetch_playwright_html(url, referer, wait_puzzle=wait_puzzle, autoclick=autoclick)
                        if isinstance(r, dict):
                            res.update(r)
                    except Exception:
                        pass
                if (not res.get("ok")) or (not res.get("html")):
                    code, final_url, html = fetch_raw_with_meta(url, referer)
                    res.update({
                        "ok": True,
                        "code": code,
                        "final_url": final_url,
                        "html": html,
                        "bot_protection": is_bot_protection(html) if isinstance(html, str) else False,
                    })
                return self._send_json(200, res)
            if path == '/compare':
                ean = (payload.get('ean') or '').strip()
                attach = str(payload.get('attach') or '1').lower() in ('1','true','yes')
                nopuzzle = str(payload.get('nopuzzle') or '1').lower() in ('1','true','yes')
                stores = payload.get('stores')
                stores = [s.strip() for s in stores.split(',')] if stores else None
                if not ean:
                    return self._send_json(400, {"ok": False, "error": "missing ean"})
                res = _compare_ean(ean, attach=attach, nopuzzle=nopuzzle, stores=stores)
                return self._send_json(200, res)
            return self._send_json(404, {"ok": False, "error": "not found"})
        except Exception as e:
            return self._send_json(500, {"ok": False, "error": str(e)})

def extract_ean_generic(html: str) -> str:
    """
    Extraction générique d’EAN/GTIN depuis:
    - JSON-LD (gtin13/gtin14/gtin/ean),
    - microdata/meta itemprop,
    - attributs data-*,
    - clés JSON dans scripts,
    - paramètres d’URL.
    """
    if not html:
        return None
    import json
    try:
        blocks = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>', html, re.I)
        for raw in blocks:
            txt = raw.strip()
            txt = re.sub(r',\s*([}\]])', r'\1', txt)  # tolère virgules traînantes
            try:
                data = json.loads(txt)
            except Exception:
                continue
            stack = [data]
            while stack:
                cur = stack.pop()
                if isinstance(cur, dict):
                    for key in ('gtin13', 'gtin14', 'gtin', 'ean'):
                        v = cur.get(key)
                        if v is None:
                            continue
                        m = re.search(r'(\d{8,14})', str(v))
                        if m:
                            return m.group(1)
                    for v in cur.values():
                        if isinstance(v, (dict, list)):
                            stack.append(v)
                elif isinstance(cur, list):
                    for v in cur:
                        if isinstance(v, (dict, list)):
                            stack.append(v)
    except Exception:
        pass
    # 2) Microdata/meta
    m = re.search(r'itemprop=["\'](?:gtin13|gtin|ean)["\'][^>]*content=["\'](\d{8,14})["\']', html, re.I)
    if m:
        return m.group(1)
    # 3) data-attributes
    m = re.search(r'(?:data-ean|data-gtin|data-gtin13)\s*=\s*["\'](\d{8,14})["\']', html, re.I)
    if m:
        return m.group(1)
    # 4) Clés JSON simples
    m = re.search(r'["\'](?:ean|gtin13|gtin|barcode)["\']\s*:\s*["\']?(\d{8,14})["\']?', html, re.I)
    if m:
        return m.group(1)
    # 5) Paramètres d’URL
    m = re.search(r'[?&;]ean=(\d{8,14})\b', html, re.I)
    if m:
        return m.group(1)
    return None
# Ajout des imports manquants
import re
import sys
# --- Stubs utilitaires pour éviter les erreurs de compilation ---
import types
def norm_price(val):
    try:
        return float(str(val).replace(',', '.').replace('€','').strip())
    except Exception:
        return None

def html_to_text(html):
    # Extraction très basique du texte brut
    import re
    return re.sub('<[^<]+?>', '', html or '')

def extract_ean_generic(html: str) -> str:
    """
    Extraction générique d’EAN/GTIN depuis:
    - JSON-LD (gtin13/gtin14/gtin/ean),
    - microdata/meta itemprop,
    - attributs data-*,
    - clés JSON dans scripts,
    - paramètres d’URL.
    """
    if not html:
        return None
    import json
    try:
        blocks = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>', html, re.I)
        for raw in blocks:
            txt = raw.strip()
            txt = re.sub(r',\s*([}\]])', r'\1', txt)  # tolère virgules traînantes
            try:
                data = json.loads(txt)
            except Exception:
                continue
            stack = [data]
            while stack:
                cur = stack.pop()
                if isinstance(cur, dict):
                    for key in ('gtin13', 'gtin14', 'gtin', 'ean'):
                        v = cur.get(key)
                        if v is None:
                            continue
                        m = re.search(r'(\d{8,14})', str(v))
                        if m:
                            return m.group(1)
                    for v in cur.values():
                        if isinstance(v, (dict, list)):
                            stack.append(v)
                elif isinstance(cur, list):
                    for v in cur:
                        if isinstance(v, (dict, list)):
                            stack.append(v)
    except Exception:
        pass
    # 2) Microdata/meta
    m = re.search(r'itemprop=["\'](?:gtin13|gtin|ean)["\'][^>]*content=["\'](\d{8,14})["\']', html, re.I)
    if m:
        return m.group(1)
    # 3) data-attributes
    m = re.search(r'(?:data-ean|data-gtin|data-gtin13)\s*=\s*["\'](\d{8,14})["\']', html, re.I)
    if m:
        return m.group(1)
    # 4) Clés JSON simples
    m = re.search(r'["\'](?:ean|gtin13|gtin|barcode)["\']\s*:\s*["\']?(\d{8,14})["\']?', html, re.I)
    if m:
        return m.group(1)
    # 5) Paramètres d’URL
    m = re.search(r'[?&;]ean=(\d{8,14})\b', html, re.I)
    if m:
        return m.group(1)
    return None


# Helper: bucketise price keys for unit/total
PRICE_UNIT_HINTS = ('unit', 'per', 'kilo', 'kg', 'litre', 'liter', 'dose', 'lavage')

def price_from_scripts(html: str):
    best_total = None
    unit_candidates = []

    # Centimes avec nom de clé — ex: "priceInCents", "sellingPriceInCents", éviter unit/per
    for m in re.finditer(r'(?i)"(?P<key>[^"\n]*price[^"\n]*inCents)"\s*:\s*(?P<val>\d{2,7})', html or ""):
        key = m.group('key').lower()
        val = m.group('val')
        try:
            v = round(int(val) / 100.0, 2)
        except Exception:
            continue
        if any(h in key for h in PRICE_UNIT_HINTS):
            unit_candidates.append(v)
            continue
        if 0.2 <= v <= 200 and (best_total is None or v < best_total):
            best_total = v

    # Prix flottant "price": "9,09" — éviter unit/per dans la clé
    for m in re.finditer(r'(?i)"(?P<key>[^"\n]*price[^"\n]*)"\s*:\s*"?(?P<val>\d+(?:[.,]\d{1,2}))"?', html or ""):
        key = m.group('key').lower()
        v = norm_price(m.group('val'))
        if not v:
            continue
        if any(h in key for h in PRICE_UNIT_HINTS):
            unit_candidates.append(v)
            continue
        if 0.2 <= v <= 200 and (best_total is None or v < best_total):
            best_total = v
# Stub minimal pour soup_or_text (à remplacer par la vraie logique si besoin)
def soup_or_text(html):
    return None, html_to_text(html)

    # "formattedPrice": "9,09 €" — ignorer les libellés unitaires
    for m in re.finditer(r'"formattedPrice"\s*:\s*"([^"\n]*[0-9][.,][0-9]{1,2}[^"]*)"', html or ""):
        s = m.group(1)
        if re.search(r'/\s*(?:l|kg|dose|lavage)|par\s*(?:l|kg|dose|lavage)', s, re.I):
            continue
        v = norm_price(s)
        if v and 0.2 <= v <= 200 and (best_total is None or v < best_total):
            best_total = v

    if best_total is not None:
        return None, best_total
    # Aucun total fiable. On laisse la détection HTML prendre le relai.
    return None, None

def price_from_html(html: str):
    soup, text = soup_or_text(html)
    candidates = []
    title = None
    if soup is not None:
        if soup.title:
            title = (soup.title.text or "").strip()
        for meta in soup.select('meta[itemprop="price"]'):
            if meta and meta.get("content"):
                v = norm_price(meta.get("content"))
                if v and 0.2 <= v <= 200:
                    candidates.append(v)
        for el in soup.select('span[class*="price"], div[class*="price"] span, span[class*="BasePrice"], span[class*="base-price"], [data-price]'):
            txt = (el.get("data-price") or el.get_text(" ").strip())
            v = norm_price(str(txt))
            if v and 0.2 <= v <= 200:
                candidates.append(v)
        text = soup.get_text(" ", strip=True)
    else:
        for mm in re.finditer(r"<meta[^>]*itemprop=\"price\"[^>]*content=\"([^\"]+)\"[^>]*>", html or "", re.I):
            v = norm_price(mm.group(1))
            if v and 0.2 <= v <= 200:
                candidates.append(v)
        text = html_to_text(html)
    for m in re.finditer(r"(?:([0-9]+[.,][0-9]{1,2})\s*(?:€|\u20AC)|(?:€|\u20AC)\s*([0-9]+[.,][0-9]{1,2}))", text or ""):
        s = m.group(1) or m.group(2)
        tail = (text[m.end():m.end()+12] or '').lower()
        if ('/l' in tail) or ('par l' in tail) or ('/kg' in tail) or ('par kg' in tail) or ('/dose' in tail) or ('par dose' in tail):
            continue
        v = norm_price(s)
        if v and 0.2 <= v <= 200:
            candidates.append(v)
    # Forme "9 € 09" (euros et centimes séparés)
    for m in re.finditer(r"\b(\d{1,3})\s*(?:€|\u20AC)\s*(\d{2})\b", text or ""):
        tail = (text[m.end():m.end()+12] or '').lower()
        if ('/l' in tail) or ('par l' in tail) or ('/kg' in tail) or ('par kg' in tail) or ('/dose' in tail) or ('par dose' in tail):
            continue
        s = f"{m.group(1)},{m.group(2)}"
        v = norm_price(s)
        if v and 0.2 <= v <= 200:
            candidates.append(v)
    if candidates:
        # Choisir le PLUS GRAND montant plausible pour éviter de prendre unitaire (ex: 1,09 €/dose) au lieu du total (ex: 9,09 €)
        return title, max(candidates)
    return None, None

# Helper: scan amounts in html that are not immediately followed by unit (€/kg, €/l, /dose, etc)
def _scan_amounts_no_unit(html: str):
    """Retourne une liste de montants € visibles qui ne sont pas suivis de /kg, /l, /dose dans l'immédiat."""
    soup, text = soup_or_text(html)
    if soup is not None:
        text = soup.get_text(" ", strip=True)
    amounts = []
    for m in re.finditer(r"(?:([0-9]+[.,][0-9]{1,2})\s*(?:€|\u20AC)|(?:€|\u20AC)\s*([0-9]+[.,][0-9]{1,2}))", text or ""):
        s = m.group(1) or m.group(2)
        tail = (text[m.end():m.end()+18] or '').lower()
        if any(k in tail for k in [' /l', '/l', ' par l', ' /kg', '/kg', ' par kg', ' /dose', '/dose', ' par dose', ' lavage']):
            continue
        v = norm_price(s)
        if v and 0.2 <= v <= 200:
            amounts.append(v)
    return amounts

def parse_liters_from_text(text: str):
    m = re.search(r"(\\d+(?:[.,]\\d+)?)\\s*(?:l|L)\\b", text or "")
    if m:
        try:
            return float(m.group(1).replace(',', '.'))
        except Exception:
            return None
    return None

def extract_unit_price_per_liter(html: str):
    soup, txt = soup_or_text(html)
    if soup is not None:
        txt = soup.get_text(" ", strip=True)
    # Éviter de confondre "/l" avec "/lavage" : exiger frontière ou mots explicites
    patterns = [
        r"(\d+[.,]\d{1,2})\s*€\s*\/\s*(?:[lL](?!avage)\b|litre|liter)\b",
        r"(\d+[.,]\d{1,2})\s*€\s*par\s*(?:[lL](?!avage)\b|litre|liter)\b",
    ]
    for rgx in patterns:
        m = re.search(rgx, txt or "", re.I)
        if m:
            v = norm_price(m.group(1))
            if v and 0.2 <= v <= 200:
                return v
    return None

def parse_weight_kg_from_text(text: str):
    m = re.search(r"(\\d+(?:[.,]\\d+)?)\\s*(kg|g)\\b", text or "", re.I)
    if not m:
        return None
    val = float(m.group(1).replace(',', '.'))
    return val if m.group(2).lower() == 'kg' else val / 1000.0

# Helper: extract all plausible weights in kg from text
def parse_weights_kg_all(text: str):
    vals = []
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(kg|g)\b", text or "", re.I):
        try:
            v = float(m.group(1).replace(',', '.'))
            if m.group(2).lower() == 'g':
                v = v / 1000.0
            if 0.05 <= v <= 5.0:  # bornes plausibles pack conso
                vals.append(round(v, 3))
        except Exception:
            pass
    return vals

def extract_unit_price_per_kg(html: str):
    soup, txt = soup_or_text(html)
    if soup is not None:
        txt = soup.get_text(" ", strip=True)
    # 1) Texte visible
    for rgx in [
        r"(\d+[.,]\d{1,2})\s*€\s*[\u00A0\s]*\/[\u00A0\s]*kg",
        r"(\d+[.,]\d{1,2})\s*€\/(?:\s*)kg",
        r"(\d+[.,]\d{1,2})\s*€\s*par\s*kg",
    ]:
        m = re.search(rgx, txt or "", re.I)
        if m:
            v = norm_price(m.group(1))
            if v and 0.2 <= v <= 999:
                return v
    # 2) JSON hints (Auchan/Carrefour)
    for rgx in [
        r'"pricePerKg"\s*:\s*"?(\d+(?:[.,]\d{1,2}))"?',
        r'"unitPrice"\s*:\s*"?(\d+(?:[.,]\d{1,2}))"?\s*,\s*"unitOfMeasure"\s*:\s*"(?:KG|KILOGRAM)"',
        r'"pricePerUnitFormatted"\s*:\s*"(\d+(?:[.,]\d{1,2})).{0,20}kg"',
    ]:
        m = re.search(rgx, html or "", re.I)
        if m:
            v = norm_price(m.group(1))
            if v and 0.2 <= v <= 999:
                return v
    return None

def parse_count_from_text(text: str):
    if not text:
        return None
    # Ex: "20 capsules", "14 pods", "26 lavages"
    m = re.search(r"\b(\d{1,3})\s*(?:caps?(?:ule|ules)?|dosettes?|doses?|pod|pods|lavage|lavages?|tablette|tablettes)\b", text, re.I)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    # Ex: "x20 capsules" ou "x 22 lavages" ou "× 26 pods"
    m = re.search(r"\b(?:x|×)\s*(\d{1,3})\b\s*(?:caps?(?:ule|ules)?|dosettes?|doses?|pod|pods|lavage|lavages?|tablette|tablettes)\b", text, re.I)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    # Ex: "26 x capsules" ou "26× dosettes"
    m = re.search(r"\b(\d{1,3})\s*(?:x|×)\s*(?:caps?(?:ule|ules)?|dosettes?|doses?|pod|pods|lavage|lavages?|tablette|tablettes)\b", text, re.I)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass
    # Ex: "26 pcs", "26 pièces", "26 unites", "boîte de 26", "pack de 26"
    for rgx in [
        r"\b(\d{1,3})\s*(?:pcs?|pi[eè]ces?)\b",
        r"\b(\d{1,3})\s*(?:unit[eé]s?)\b",
        r"\b(?:pack|bo[iî]te)\s*(?:de|of)\s*(\d{1,3})\b",
    ]:
        m = re.search(rgx, text, re.I)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return None

def extract_unit_price_per_dose(html: str):
    soup, txt = soup_or_text(html)
    if soup is not None:
        txt = soup.get_text(" ", strip=True)
    for rgx in [
        r"(\d+[.,]\d{1,2})\s*€\s*\/\s*(?:dose|doses?|lavage|lavages?|caps?(?:ule|ules)?|pod|pods|tablette|tablettes)\b",
        r"(\d+[.,]\d{1,2})\s*€\s*par\s*(?:dose|doses?|lavage|lavages?|caps?(?:ule|ules)?|pod|pods|tablette|tablettes)\b",
    ]:
        m = re.search(rgx, txt or "", re.I)
        if m:
            v = norm_price(m.group(1))
            if v and 0.01 <= v <= 10:
                return v
    return None

def first_price_before_marker(html: str):
    soup, txt = soup_or_text(html)
    if soup is not None:
        txt = soup.get_text(" ", strip=True)
    lower = (txt or "").lower(); cut = len(txt or "")
    for t in ['vous aimerez aussi', 'produits similaires', 'ils achètent aussi', 'vous pourriez aussi aimer']:
        i = lower.find(t)
        if i != -1 and i < cut:
            cut = i
    txt2 = (txt or "")[:cut]
    for m in re.finditer(r"(\d{1,3}(?:[.,]\d{1,2}))\s*€", txt2 or ""):
        end = m.end(); tail = (txt2[end:end+12] or '').lower()
        if '/l' in tail or 'par l' in tail:
            continue
        v = norm_price(m.group(1))
        if v and 0.2 <= v <= 200:
            return v
# Helper to accept cookie consent banners
def _accept_consent(page):
    selectors = [
        "button:has-text(\"Tout accepter\")",
        "button:has-text(\"Accepter\")",
        "button:has-text(\"J'accepte\")",
        "[id^=didomi] button:has-text(\"Accepter\")",
        "[id*='consent'] button:has-text(\"Accepter\")",
        ".didomi-continue-without-agreeing",
        "button[aria-label='Tout accepter']",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.click(timeout=1500)
                page.wait_for_timeout(500)
                break
        except Exception:
            pass
    return None

# Helper: wait for human to solve bot puzzle if present
def _wait_if_bot_puzzle(page, label="bot/puzzle", timeout_ms=180000):
    """Attend qu'un éventuel mur/puzzle anti-bot soit résolu manuellement.
    Ramène l'onglet au premier plan et boucle jusqu'à disparition des marqueurs.
    Retourne True si la barrière semble levée avant timeout, sinon False.
    """
    try:
        page.bring_to_front()
    except Exception:
        pass
    deadline = time.time() + (timeout_ms / 1000.0)
    last_note = 0.0
    while time.time() < deadline:
        try:
            html = page.content()
        except Exception:
            html = ""
        if html and not is_bot_protection(html):
            try:
                page.wait_for_load_state('networkidle', timeout=2000)
            except Exception:
                pass
            return True
        # Message console périodique pour guider l'opérateur
        now = time.time()
        if now - last_note > 10:
            try:
                page.evaluate("console.log('[maxicourses] Résoudre le puzzle anti-bot si présent, puis attendre le chargement...')")
            except Exception:
                pass
            last_note = now
        try:
            page.wait_for_timeout(800)
        except Exception:
            pass
    return False

# Helper: Carrefour — rendre le prix visible (ouvrir options d'achat et choisir une option si nécessaire)
def _carrefour_make_price_visible(page, url: str):
    try:
        u = (page.url or url or "").lower()
        if "carrefour.fr" not in u:
            return
        # Si un meta price est déjà présent, rien à faire
        try:
            if page.locator('meta[itemprop="price"]').count() > 0:
                return
        except Exception:
            pass

        # Variantes de libellés
        labels = [
            "options d'achat",
            "options d’achat",
            "voir les options",
            "voir les disponibilités",
            "choisir un magasin",
            "voir les options d'achat",
            "voir les options d’achat",
        ]
        # Essayer de cliquer sur un déclencheur
        for txt in labels:
            try:
                loc = page.locator(f'button:has-text("{txt}")')
                if loc.count() == 0:
                    loc = page.locator(f'a:has-text("{txt}")')
                if loc.count() > 0:
                    loc.first.click(timeout=2500)
                    page.wait_for_timeout(600)
                    break
            except Exception:
                pass

        # Si un modal est ouvert, essayer de choisir une option puis valider
        try:
            modal = page.locator('[role="dialog"], [data-modal], .modal, [class*="modal"]')
            if modal.count() > 0:
                # Essayer les boutons Drive/Livraison ou premier bouton d’action
                choices = [
                    'button:has-text("Drive")',
                    'button:has-text("Livraison")',
                    'button:has-text("Valider")',
                    'button:has-text("Continuer")',
                    'button',
                ]
                for sel in choices:
                    try:
                        b = modal.locator(sel)
                        if b.count() > 0:
                            b.first.click(timeout=2000)
                            page.wait_for_timeout(600)
                            break
                    except Exception:
                        pass
        except Exception:
            pass

        # Attendre l’apparition d’un prix (meta price ou motif visible)
        try:
            if page.locator('meta[itemprop="price"]').count() == 0:
                # Attendre un texte euros classique
                page.wait_for_timeout(800)
        except Exception:
            pass
    except Exception:
        pass

# Helper: Carrefour autoclick from search results
def _carrefour_autoclick_product(page, url: str) -> bool:
    try:
        # Parse query to extract numbers/tokens for scoring
        u = urlsplit(url)
        q = (parse_qs(u.query).get("q") or [""])[0].lower()
        if not q:
            q = (parse_qs(u.query).get("text") or [""])[0].lower()
        raw = re.sub(r"[%+]+", " ", q)
        tokens = [t for t in re.split(r"[\s_\-]+", raw) if t]
        nums = re.findall(r"\d+", raw)

        def _score(txt: str) -> int:
            txt = (txt or "").lower()
            score = 0
            # brand / form / variant
            if "ariel" in txt: score += 3
            if re.search(r"\b(?:pods?|capsules?)\b", txt): score += 2
            if re.search(r"\b(?:3en1|3 en 1|3-in-1|3in1)\b", txt): score += 2
            # quantity (x19 / 19 capsules)
            if re.search(r"\b(?:x|×)\s*19\b", txt) or re.search(r"\b19\s*(?:capsules?|lavages?)\b", txt):
                score += 3
            # numbers from the query (e.g. 19, 70...)
            for nstr in nums:
                if nstr and nstr in txt: score += 1
            # small penalty on sponsored cards
            if "sponsorisé" in txt or "sponsoris" in txt: score -= 1
            return score

        # If anchors not present quickly, try to use the site's search box rather than relying only on URL params
        try:
            page.wait_for_selector('a[href^="/p/"]', timeout=6000)
        except Exception:
            # Try filling the on-site search input
            try:
                # Common inputs on Carrefour
                search_input = None
                for sel in [
                    'input[type="search"]',
                    'input[name="search"]',
                    'input[aria-label*="Rechercher"]',
                ]:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        search_input = loc.first
                        break
                if search_input is not None and tokens:
                    search_input.fill(" ".join(tokens)[:80], timeout=1500)
                    page.keyboard.press('Enter')
                    page.wait_for_selector('a[href^="/p/"]', timeout=12000)
            except Exception:
                pass

        links = page.locator('a[href^="/p/"]')
        n = min(links.count(), 60)
        best_idx = -1
        best_score = -10
        best_href = None
        for i in range(n):
            link = links.nth(i)
            try:
                href = link.get_attribute("href") or ""
            except Exception:
                href = ""
            # Prefer the <article> ancestor text; fallback to link text
            try:
                txt = link.evaluate('el => (el.closest("article")?.innerText || el.innerText)') or ""
            except Exception:
                try:
                    txt = link.inner_text(timeout=800)
                except Exception:
                    txt = ""
            s = _score(txt)
            if s > best_score:
                best_score = s
                best_idx = i
                best_href = href

        if best_idx >= 0 and best_score >= 3:
            link = links.nth(best_idx)
            try:
                link.scroll_into_view_if_needed(timeout=1500)
            except Exception:
                pass
            try:
                link.click(timeout=3000, force=True)
            except Exception:
                # Fallback: navigate directly if click blocked
                if best_href:
                    try:
                        page.goto("https://www.carrefour.fr" + best_href, wait_until="domcontentloaded")
                    except Exception:
                        pass

            # Ensure we ended up on a product page
            try:
                page.wait_for_url(re.compile(r"https://www\.carrefour\.fr/p/.*"), timeout=12000)
            except Exception:
                if best_href:
                    try:
                        page.evaluate('url => window.location.assign(url)', "https://www.carrefour.fr" + best_href)
                        page.wait_for_url(re.compile(r"https://www\.carrefour\.fr/p/.*"), timeout=8000)
                    except Exception:
                        pass
            try:
                cur = page.url or ""
            except Exception:
                cur = ""
            return "/p/" in cur

        return False
    except Exception:
        return False

def _score_from_query(url: str):
    """Build lightweight scoring tokens from a search URL (q= or text= or /recherche/...)."""
    try:
        u = urlsplit(url)
        q = (parse_qs(u.query).get("q") or parse_qs(u.query).get("text") or [""])[0].lower()
        if not q:
            m = re.search(r"/recherche/([^/?#]+)", u.path or "")
            if m:
                q = m.group(1).replace("+", " ")
        raw = re.sub(r"[%+]+", " ", q)
        tokens = [t for t in re.split(r"[\s_\-]+", raw) if t]
        nums = re.findall(r"\d+", raw)
        return tokens, nums
    except Exception:
        return [], []

def _score_text_generic(txt: str, tokens, nums) -> int:
    txt = (txt or "").lower()
    score = 0
    if "ariel" in txt: score += 3
    if re.search(r"\b(?:pods?|capsules?)\b", txt): score += 2
    if re.search(r"\b(?:3en1|3 en 1|3-in-1|3in1)\b", txt): score += 2
    # Variant preference: Original over Alpine when both appear in catalog
    if re.search(r"\boriginal\b", txt):
        score += 3
    if re.search(r"\balpine\b", txt):
        score -= 3
    for nstr in nums:
        if nstr and nstr in txt:
            score += 1
    for tk in tokens:
        if tk and tk in txt:
            score += 1
    if "sponsorisé" in txt or "sponsoris" in txt:
        score -= 1
    # Penalize other plausible dose counts not requested (helps prefer 19 vs 30/38)
    try:
        nums_in_txt = re.findall(r"\b(\d{1,3})\b", txt)
        wanted = set([n for n in nums if n])
        plausible = {str(n) for n in [12,14,15,16,17,18,19,20,22,24,26,28,30,32,34,36,38,40,42,45,48,50,54,57,60]}
        # Strong boost if explicit wanted count appears (e.g., x19 / 19 capsules)
        for wn in list(wanted):
            if re.search(rf"\b(?:x|×)?\s*{re.escape(wn)}\b\s*(?:capsules?|lavages?|doses?)?", txt):
                score += 8
        # Heuristic by pack weight for 19 pods (~346 g) vs 30 pods (~546 g)
        if '19' in wanted:
            if re.search(r"\b346\s*g\b", txt):
                score += 3
            if re.search(r"\b546\s*g\b", txt):
                score -= 3
        for n in nums_in_txt:
            if n in plausible and n not in wanted:
                score -= 6
    except Exception:
        pass
    return score

def _auchan_autoclick_product(page, url: str) -> bool:
    try:
        if not ("auchan.fr" in (url or "") or "auchan.fr" in (page.url or "")):
            return False
        tokens, nums = _score_from_query(url or (page.url or ""))
        sel = 'a[href*="/p-"], a[href*="/produit/"], a[href*="/pr-"]'
        page.wait_for_selector(sel, timeout=15000)
        links = page.locator(sel)
        n = min(links.count(), 80)
        best_idx = -1
        best_score = -10
        best_href = None
        for i in range(n):
            link = links.nth(i)
            try:
                href = link.get_attribute("href") or ""
            except Exception:
                href = ""
            try:
                txt = link.evaluate('el => (el.closest("article")?.innerText || el.innerText)') or ""
            except Exception:
                try:
                    txt = link.inner_text(timeout=600)
                except Exception:
                    txt = ""
            s = _score_text_generic(txt, tokens, nums)
            if s > best_score:
                best_score = s; best_idx = i; best_href = href
        if best_idx >= 0 and best_score >= 2:
            link = links.nth(best_idx)
            try:
                link.scroll_into_view_if_needed(timeout=1200)
            except Exception:
                pass
            try:
                link.click(timeout=2500, force=True)
            except Exception:
                if best_href:
                    try:
                        base = re.sub(r"^(https?://[^/]+).*", r"\\1", page.url or url)
                        page.goto(base + best_href, wait_until="domcontentloaded")
                    except Exception:
                        pass
            try:
                page.wait_for_url(re.compile(r"https://[^/]*auchan\.fr/.+/(?:p-\d+|produit|p/|pr-[^/?#]+)"), timeout=10000)
            except Exception:
                pass
            try:
                cur = page.url or ""
            except Exception:
                cur = ""
            return bool(re.search(r"https://[^/]*auchan\.fr/.+/(?:p-\d+|produit|p/)", cur))
    except Exception:
        pass
    return False

def _intermarche_autoclick_product(page, url: str) -> bool:
    try:
        if not ("intermarche.com" in (url or "") or "intermarche.com" in (page.url or "")):
            return False
        tokens, nums = _score_from_query(url or (page.url or ""))
        sel = 'a[href*="/produit/"], a[href*="/p/"]'
        page.wait_for_selector(sel, timeout=15000)
        links = page.locator(sel)
        n = min(links.count(), 80)
        best_idx = -1
        best_score = -10
        best_href = None
        had_strict_match = False
        for i in range(n):
            link = links.nth(i)
            try:
                href = link.get_attribute("href") or ""
            except Exception:
                href = ""
            try:
                txt = link.evaluate('el => (el.closest("article")?.innerText || el.innerText)') or ""
            except Exception:
                try:
                    txt = link.inner_text(timeout=600)
                except Exception:
                    txt = ""
            s = _score_text_generic(txt, tokens, nums)
            # If query contains a target count (e.g. 19), require its presence in text to consider clicking
            require = None
            for nstr in nums:
                if nstr:
                    require = nstr; break
            strict_ok = True
            if require is not None and require.strip():
                strict_ok = bool(re.search(rf"\b(?:x|×)?\s*{re.escape(require)}\b", txt.lower()))
            if strict_ok:
                had_strict_match = True
            else:
                s -= 50  # strongly demote cards without the requested count
            if s > best_score:
                best_score = s; best_idx = i; best_href = href
        # If nothing matched strictly (e.g. cards don't show counts), avoid clicking a wrong pack
        if not had_strict_match:
            return False
        if best_idx >= 0 and best_score >= 2:
            link = links.nth(best_idx)
            try:
                link.scroll_into_view_if_needed(timeout=1200)
            except Exception:
                pass
            try:
                link.click(timeout=2500, force=True)
            except Exception:
                if best_href:
                    try:
                        base = re.sub(r"^(https?://[^/]+).*", r"\\1", page.url or url)
                        page.goto(base + best_href, wait_until="domcontentloaded")
                    except Exception:
                        pass
            try:
                page.wait_for_url(re.compile(r"https://[^/]*intermarche\.com/.+/(?:produit|p)/"), timeout=10000)
            except Exception:
                pass
            try:
                cur = page.url or ""
            except Exception:
                cur = ""
            return bool(re.search(r"https://[^/]*intermarche\.com/.+/(?:produit|p)/", cur))
    except Exception:
        pass
    return False

def _monoprix_autoclick_product(page, url: str) -> bool:
    try:
        u = page.url or url or ""
        if not ("monoprix.fr" in u or "courses.monoprix.fr" in u):
            return False
        tokens, nums = _score_from_query(u)
        sel = 'a[href*="/p/"], a[href*="/produit/"]'
        page.wait_for_selector(sel, timeout=15000)
        links = page.locator(sel)
        n = min(links.count(), 80)
        best_idx = -1
        best_score = -10
        best_href = None
        for i in range(n):
            link = links.nth(i)
            try:
                href = link.get_attribute("href") or ""
            except Exception:
                href = ""
            try:
                txt = link.evaluate('el => (el.closest("article")?.innerText || el.innerText)') or ""
            except Exception:
                try:
                    txt = link.inner_text(timeout=600)
                except Exception:
                    txt = ""
            s = _score_text_generic(txt, tokens, nums)
            if s > best_score:
                best_score = s; best_idx = i; best_href = href
        if best_idx >= 0 and best_score >= 2:
            link = links.nth(best_idx)
            try:
                link.scroll_into_view_if_needed(timeout=1200)
            except Exception:
                pass
            try:
                link.click(timeout=2500, force=True)
            except Exception:
                if best_href:
                    try:
                        base = re.sub(r"^(https?://[^/]+).*", r"\\1", page.url or url)
                        page.goto(base + best_href, wait_until="domcontentloaded")
                    except Exception:
                        pass
            try:
                page.wait_for_url(re.compile(r"https://[^/]*monoprix\.fr/.*/p/\d+|https://courses\.monoprix\.fr/.*/p/\d+"), timeout=10000)
            except Exception:
                pass
            try:
                cur = page.url or ""
            except Exception:
                cur = ""
            return bool(re.search(r"https://[^/]*monoprix\.fr/.*/p/\d+|https://courses\.monoprix\.fr/.*/p/\d+", cur))
    except Exception:
        pass
    return False

def extract_ean_leclerc(html: str) -> str:
    """
    Extrait le code EAN d'une page produit Leclerc Drive.
    Cherche dans le bloc 'informations pratiques' ou dans les liens vers la fiche produit.
    """
    # 1) Cherche un lien vers la fiche produit contenant l'EAN (ex: ?ean=8006540027277)
    m = re.search(r'[?&;]ean=(\d{8,14})\b', html)
    if m:
        return m.group(1)
    # 2) Cherche un bloc "EAN : 8006540027277" dans la section informations pratiques
    m = re.search(r'\bEAN\s*[:：]\s*(\d{8,14})\b', html)
    if m:
        return m.group(1)
    # 3) Cherche dans les balises meta ou data-ean éventuelles
    m = re.search(r'(?:data-ean|itemprop="gtin13"|itemprop="ean")\s*[:=]\s*["\']?(\d{8,14})["\']?', html)
    if m:
        return m.group(1)
    return None

# ...tout le reste du code...

def run_server(bind: str = "127.0.0.1:5001"):
    try:
        host, port = bind.split(":")
        port = int(port)
    except Exception:
        host, port = "127.0.0.1", 5001
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"[maxicourses] Serveur démarré sur http://{host}:{port}")
    print("[maxicourses] Endpoints: /health, /scrape, /fetch, /compare")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            httpd.server_close()
        except Exception:
            pass
        print("\n[maxicourses] Serveur arrêté.")

if __name__ == "__main__":
    if "--serve" in sys.argv:
        i = sys.argv.index("--serve")
        bind = sys.argv[i + 1] if i + 1 < len(sys.argv) else "127.0.0.1:5001"
        run_server(bind)
    else:
        
        def extract_ean_generic(html: str) -> str:        main()
        
    """
    Extraction générique d’EAN/GTIN depuis:
    - JSON-LD (gtin13/gtin14/gtin/ean),
    - microdata/meta itemprop,
    - attributs data-*,
    - clés JSON dans scripts,
    - paramètres d’URL.
    """
def extract_ean_generic(html: str) -> str:
    """
    Extraction générique d’EAN/GTIN depuis:
    - JSON-LD (gtin13/gtin14/gtin/ean),
    - microdata/meta itemprop,
    - attributs data-*,
    - clés JSON dans scripts,
    - paramètres d’URL.
    """
    if not html:
        return None
    # 1) JSON-LD
    try:
        blocks = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>', html, re.I)
        for raw in blocks:
            txt = raw.strip()
            txt = re.sub(r',\s*([}\]])', r'\1', txt)  # tolère virgules traînantes
            try:
                data = json.loads(txt)
            except Exception:
                continue
            stack = [data]
            while stack:
                cur = stack.pop()
                if isinstance(cur, dict):
                    for key in ('gtin13', 'gtin14', 'gtin', 'ean'):
                        v = cur.get(key)
                        if v is None:
                            continue
                        m = re.search(r'(\d{8,14})', str(v))
                        if m:
                            return m.group(1)
                    for v in cur.values():
                        if isinstance(v, (dict, list)):
                            stack.append(v)
                elif isinstance(cur, list):
                    for v in cur:
                        if isinstance(v, (dict, list)):
                            stack.append(v)
    except Exception:
        pass
    # 2) Microdata/meta
    m = re.search(r'itemprop=["\'](?:gtin13|gtin|ean)["\'][^>]*content=["\'](\d{8,14})["\']', html, re.I)
    if m:
        return m.group(1)
    # 3) data-attributes
    m = re.search(r'(?:data-ean|data-gtin|data-gtin13)\s*=\s*["\'](\d{8,14})["\']', html, re.I)
    if m:
        return m.group(1)
    # 4) Clés JSON simples
    m = re.search(r'["\'](?:ean|gtin13|gtin|barcode)["\']\s*:\s*["\']?(\d{8,14})["\']?', html, re.I)
    if m:
        return m.group(1)
    # 5) Paramètres d’URL
    m = re.search(r'[?&;]ean=(\d{8,14})\b', html, re.I)
    if m:
        return m.group(1)
    return None
    # 2) Microdata/meta
    m = re.search(r'itemprop=["\'](?:gtin13|gtin|ean)["\'][^>]*content=["\'](\d{8,14})["\']', html, re.I)
    if m:
        return m.group(1)
    # 3) data-attributes
    m = re.search(r'(?:data-ean|data-gtin|data-gtin13)\s*=\s*["\'](\d{8,14})["\']', html, re.I)
    if m:
        return m.group(1)
    # 4) Clés JSON simples
    m = re.search(r'["\'](?:ean|gtin13|gtin|barcode)["\']\s*:\s*["\']?(\d{8,14})["\']?', html, re.I)
    if m:
        return m.group(1)
    # 5) Paramètres d’URL
    m = re.search(r'[?&;]ean=(\d{8,14})\b', html, re.I)
    if m:
        return m.group(1)
    return None

def extract_from_html_common(html: str, title_hint: str, host: str):
    # Store-specific DOM shortcuts (price article total)
    price = None
    title = None
    price_authoritative = False
    ean = None  # <-- Ajout extraction EAN
    try:
        h = (host or '').lower()
        if ('leclercdrive' in h) or ('leclerc.fr' in h):
            # Extraction EAN
            ean = extract_ean_leclerc(html)
            # 1) Nouvelle structure : <span class="main-price">8,99 €</span>
            try:
                m = re.search(r'<span[^>]+class="[^"]*main-price[^"]*"[^>]*>([\d\s,]+)[^<]*</span>', html, re.I)
                if m:
                    price = norm_price(m.group(1))
                    price_authoritative = True
            except Exception:
                pass
            # 2) Ancienne structure : <div class="prix">...</div>
            if price is None:
                try:
                    blk = re.search(r"<div[^>]+class=\"[^\"]*\bprix\b[^\"]*\"[^>]*>(.*?)</div>", html, re.I | re.S)
                    if blk:
                        b = blk.group(1)
                        mi = re.search(r"prix-actuel-partie-entiere[^>]*>\s*(\d{1,3})\s*<", b, re.I)
                        md = re.search(r"prix-actuel-partie-decimale[^>]*>\s*,?(\d{2})\s*<", b, re.I)
                        if mi and md:
                            price = float(f"{mi.group(1)}.{md.group(1)}")
                            price_authoritative = True
                except Exception:
                    price = None
            # 3) Fallback: data-track-action ... price=9.09
            if price is None:
                m2 = re.search(r'data-track-action=["\'][^"\']*\bprice=([0-9]+(?:\.[0-9]+)?)\b', html, re.I)
                if m2:
                    try:
                        price = float(m2.group(1))
                        price_authoritative = True
                    except Exception:
                        price = None
        # Auchan: extraire le prix affiché (éviter de déduire depuis €/kg)
        if price is None and ('auchan.fr' in h):
            try:
                # Pattern visuel (bloc prix)
                m = re.search(r"(?:product-price[^<]*|price__current|price__amount|price__main)[^>]*>[^€]*?([0-9]{1,3},[0-9]{2})\s*€", html, re.I)
                if m:
                    v = norm_price(m.group(1))
                    if v and 0.2 <= v <= 200:
                        price = v
                        price_authoritative = True
                if price is None:
                    # schema.org Product
                    m2 = re.search(r"<meta[^>]+itemprop=\"price\"[^>]+content=\"([^\"]+)\"", html, re.I)
                    if m2:
                        v = norm_price(m2.group(1))
                        if v and 0.2 <= v <= 200:
                            price = v
                            price_authoritative = True
            except Exception:
                pass
        # Carrefour: utilise l'extracteur dédié (JSON-LD/scripts/meta)
        if price is None and ('carrefour.fr' in h):
            try:
                from stores import carrefour as cf
                tcarf, pcarf = cf.extract_price_and_title(html, '')
                if pcarf is not None and 0.2 <= pcarf <= 200:
                    price = pcarf
                    price_authoritative = True
                    if title is None and tcarf:
                        title = tcarf
                uk = cf.extract_unit_price_per_kg(html)
                if uk is not None and uk > 0:
                    # initialize unit_hint if absent
                    if 'unit_hint' not in locals() or not isinstance(unit_hint, dict):
                        unit_hint = {"per_liter": None, "liters": None, "per_kg": None, "kg": None, "per_dose": None, "doses": None}
                    unit_hint["per_kg"] = round(uk, 2)
            except Exception:
                pass
    except Exception:
        pass

    if title is None or price is None:
        t2, p2 = price_from_jsonld(html)
        if title is None:
            title = t2
        if price is None:
            price = p2
    if price is None:
        title, price = price_from_scripts(html)
    if price is None:
        title, price = price_from_html(html)

    computed_from_liters = None
    computed_from_kg = None
    computed_from_dose = None

    unit_pl = extract_unit_price_per_liter(html)
    if unit_pl is not None:
        lit = parse_liters_from_text(title_hint or title or "")
        if lit is None:
            lit = parse_liters_from_text(html_to_text(html)[:6000])
        if lit and lit > 0:
            computed_from_liters = round(unit_pl * lit, 2)

    unit_kg = extract_unit_price_per_kg(html)
    # Carrefour: si la détection générique ne voit pas le €/kg, utiliser l'extracteur dédié
    try:
        if unit_kg is None and ('carrefour.fr' in (host or '')):
            from stores import carrefour as cf
            uk2 = cf.extract_unit_price_per_kg(html)
            if uk2 is not None:
                unit_kg = uk2
            # Tenter aussi de lire le poids du pack pour pouvoir dériver per_kg
            if 'kg' not in locals() or not locals().get('kg'):
                wkg = cf.extract_pack_weight_kg(html)
                if wkg is not None and wkg > 0:
                    kg = wkg
    except Exception:
        pass
    if unit_kg is not None:
        kg_vals = parse_weights_kg_all(title_hint or title or "")
        if not kg_vals:
            kg_vals = parse_weights_kg_all(html_to_text(html)[:6000])
        # Si Carrefour nous a donné un poids pack, l'ajouter comme candidat
        try:
            if 'kg' in locals() and kg:
                kg_vals.append(float(kg))
        except Exception:
            pass
        if kg_vals:
            # Prendre le poids le plus élevé plausible pour éviter les mini-mentions (ex: 309 g vs 346 g)
            kg = max(kg_vals)
            computed_from_kg = round(unit_kg * kg, 2)

    # Détecter le nombre de doses/capsules indépendamment d'un prix unitaire
    count_n = parse_count_from_text(title_hint or title or "")
    if count_n is None:
        count_n = parse_count_from_text(html_to_text(html)[:6000])

    unit_dose = extract_unit_price_per_dose(html)
    if unit_dose is not None and count_n:
        computed_from_dose = round(unit_dose * count_n, 2)

    # --- Unit hint dict ---
    unit_hint = {"per_liter": None, "liters": None, "per_kg": None, "kg": None, "per_dose": None, "doses": None}
    if unit_pl is not None:
        unit_hint["per_liter"] = round(unit_pl, 2)
    # liters parsed earlier in this function
    try:
        if 'lit' in locals() and lit and lit > 0:
            unit_hint["liters"] = round(lit, 3)
    except Exception:
        pass
    if unit_kg is not None:
        unit_hint["per_kg"] = round(unit_kg, 2)
    try:
        if 'kg' in locals() and kg and kg > 0:
            unit_hint["kg"] = round(kg, 3)
    except Exception:
        pass
    if unit_dose is not None:
        unit_hint["per_dose"] = round(unit_dose, 2)
    if count_n:
        unit_hint["doses"] = int(count_n)

    if 'intermarche.com' in host:
        p_first = first_price_before_marker(html)
        if p_first and price and price > p_first * 1.5:
            price = p_first

    # Heuristiques uniquement si pas de prix DOM autoritatif
    if not price_authoritative:
        try:
            amounts = _scan_amounts_no_unit(html)
            if price is not None:
                amounts.append(price)
            # Utiliser €/kg si dispo
            if unit_kg is not None:
                cand = [v for v in amounts if (0.15 * unit_kg) <= v <= (0.95 * unit_kg)]
                if cand:
                    price = max(cand)
            # Sinon utiliser €/L si dispo
            elif unit_pl is not None:
                # Les formats courants 0.5L à 3L
                cand = [v for v in amounts if (0.3 * unit_pl) <= v <= (3.2 * unit_pl)]
                if cand:
                    price = max(cand)
        except Exception:
            pass

        # Choix final du prix: privilégier les totaux calculés €/kg ou €/L s'ils sont disponibles et cohérents
        try:
            host_l = (host or '').lower()
            # 1) Si €/kg disponible + poids connu → privilégier ce total sur certaines enseignes (ex: Auchan)
            if computed_from_kg is not None and 0.2 <= computed_from_kg <= 200:
                if ('auchan.fr' in host_l):
                    price = computed_from_kg
                elif price is None or (price > computed_from_kg * 1.18):
                    # si le prix détecté est nettement supérieur, faire confiance au €/kg
                    price = computed_from_kg
            # 2) Sinon, si €/L disponible + litres connus
            elif computed_from_liters is not None and 0.2 <= computed_from_liters <= 200:
                if price is None or (price > computed_from_liters * 1.18):
                    price = computed_from_liters
            # 3) Ne jamais promouvoir le total dérivé via €/dose (souvent piégeux)
        except Exception:
            pass

    return title, price, unit_hint, ean

# ---------- Fetch + debug dump ----------

def fetch_direct(url: str, referer: str):
    cj = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cj))
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
        'Accept-Encoding': 'identity',
        'Referer': referer,
        'Connection': 'keep-alive',
    }
    # Pré-charger le site pour cookies
    try:
        pre = Request(referer, headers=headers)
        opener.open(pre, timeout=12).read()
    except Exception:
        pass

    req = Request(url, headers=headers)

    # Toujours essayer de récupérer le CORPS même en cas d'erreur HTTP (403/404/503...)
    raw = b""
    enc_header = ""
    try:
        resp = opener.open(req, timeout=20)
        raw = resp.read()
        enc_header = (resp.headers.get('Content-Encoding') or '').lower()
    except Exception as e:
        try:
            import urllib.error as urr
            if isinstance(e, urr.HTTPError):
                try:
                    raw = e.read() or b""
                    enc_header = (getattr(e, 'headers', {}) or {}).get('Content-Encoding', '').lower() if hasattr(e, 'headers') else ''
                except Exception:
                    raw = b""
            else:
                raw = b""
        except Exception:
            raw = b""

    # Décompression: si en-tête gzip inconnu (puisque resp peut être absent), détecter via magic bytes
    if not raw:
        return ""
    try:
        if 'gzip' in enc_header or (len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B):
            raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
    except Exception:
        pass

    # tentative utf-8 puis latin-1
    try:
        html = raw.decode('utf-8', errors='ignore')
    except Exception:
        try:
            html = raw.decode('latin-1', errors='ignore')
        except Exception:
            html = ""

    return html

# Helper: fetch a page and return (code, final_url, html)
def fetch_raw_with_meta(url: str, referer: str):
    """Fetch a page with browser-like headers and return (code, final_url, html)."""
    cj = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cj))
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
        'Accept-Encoding': 'identity',
        'Referer': referer or re.sub(r'^(https?://[^/]+/).*', r'\\1', url),
        'Connection': 'keep-alive',
    }
    # Preload referer for cookies
    try:
        pre = Request(headers['Referer'], headers=headers)
        opener.open(pre, timeout=12).read()
    except Exception:
        pass

    req = Request(url, headers=headers)

    raw = b""
    enc_header = ""
    code = 0
    final_url = url
    try:
        resp = opener.open(req, timeout=20)
        raw = resp.read()
        enc_header = (resp.headers.get('Content-Encoding') or '').lower()
        code = getattr(resp, 'code', 200) or 200
        final_url = getattr(resp, 'url', url) or url
    except Exception as e:
        try:
            import urllib.error as urr
            if isinstance(e, urr.HTTPError):
                code = getattr(e, 'code', 0) or 0
                try:
                    raw = e.read() or b""
                    enc_header = (getattr(e, 'headers', {}) or {}).get('Content-Encoding', '').lower() if hasattr(e, 'headers') else ''
                except Exception:
                    raw = b""
                try:
                    final_url = getattr(e, 'url', url) or url
                except Exception:
                    final_url = url
            else:
                code = 0
                raw = b""
        except Exception:
            code = 0
            raw = b""

    if raw:
        try:
            if 'gzip' in enc_header or (len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B):
                raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
        except Exception:
            pass

    # decode to text
    html = ""
    if raw:
        try:
            html = raw.decode('utf-8', errors='ignore')
        except Exception:
            try:
                html = raw.decode('latin-1', errors='ignore')
            except Exception:
                html = ""

    return code, final_url, html

def dump_debug(url: str, html: str):
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        dump_dir = os.path.join(base_dir, "debug")
        os.makedirs(dump_dir, exist_ok=True)
        host = (urlparse(url).hostname or "unknown").replace(":", "_")
        ts = time.strftime("%Y%m%d-%H%M%S")
        path = os.path.join(dump_dir, f"{host}-{ts}.html")
        with open(path, "w", encoding="utf-8", errors="ignore") as f:
            f.write(html)
        return path
    except Exception:
        return None


# Helper: détecte les pages de protection anti-bot
def is_bot_protection(html: str) -> bool:
    """
    Détecte des pages de protection anti-bot (Akamai/BotManager/Distil/Incapsula/Cloudflare, etc.)
    Retourne True si la page ressemble à une barrière anti-bot.
    """
    try:
        """Compare prices pour un EAN.

        Logique:
        1. Si EAN absent du mapping: fallback dynamique (Carrefour + Intermarché) + produit canonique si possible.
        2. Si présent: utilise les URLs connues (Leclerc direct) + recherche Carrefour (multi-slug possible) + Intermarché et ajoute produit canonique.
        """
        ean = (ean or '').strip()
        if not ean:
            return {"ok": False, "error": "missing ean"}
        wanted = [s.strip().lower() for s in stores] if stores else None
        urls_map = _PRODUCT_URLS.get(ean)

        # Produit canonique (Carrefour) – on tente toujours, erreurs ignorées
        canonical_product = None
        try:
            from .productinfo import canonical as _canonical_mod  # type: ignore
            canonical_product = _canonical_mod.get_canonical_product(ean)
        except Exception:
            canonical_product = None

        results: list[dict] = []

        def _append_carrefour(store_slug: str | None = None):
            try:
                from .stores import carrefour as _carrefour_mod
                car = _carrefour_mod.search_by_ean(ean, store_slug=store_slug, product_url=carrefour_product, store_url=carrefour_store_url, debug=debug)
            except Exception:
                car = _search_carrefour_by_ean(ean, store_slug=store_slug, product_url=carrefour_product, store_url=carrefour_store_url, debug=debug)
            if car.get('ok'):
                results.append({
                    'store': 'carrefour' if not store_slug else f'carrefour_{store_slug}',
                    'ok': True,
                    'price': car.get('price'),
                    'ean': car.get('ean'),
                    'desc': car.get('desc'),
                    'url': car.get('url'),
                    'store_slug': store_slug or car.get('store_slug'),
                    'product_forced': bool(carrefour_product),
                    'playwright': car.get('playwright'),
                    'price_source': car.get('price_source'),
                    'multi': bool(store_slug and ',' in (carrefour_store or ''))
                })
            else:
                results.append({
                    'store': 'carrefour' if not store_slug else f'carrefour_{store_slug}',
                    'ok': False,
                    'error': car.get('error'),
                    'store_slug': store_slug,
                    'multi': bool(store_slug and ',' in (carrefour_store or ''))
                })

        def _append_intermarche():
            try:
                from .stores import intermarche as _im_mod
                im = _im_mod.search_by_ean(ean, debug=debug)
            except Exception:
                im = _search_intermarche_by_ean(ean, debug=debug)
            if im.get('ok'):
                results.append({'store': 'intermarche', 'ok': True, 'price': im.get('price'), 'ean': im.get('ean'), 'desc': im.get('desc'), 'url': im.get('url')})
            else:
                results.append({'store': 'intermarche', 'ok': False, 'error': im.get('error')})

        # CAS 1: Pas de mapping => fallback dynamique
        if not urls_map:
            if wanted is None or 'carrefour' in wanted:
                _append_carrefour(carrefour_store)
            if wanted is None or 'intermarche' in wanted:
                _append_intermarche()
            out = {"ok": True, "ean": ean, "results": results, "note": "dynamic_fallback_no_mapping"}
            if canonical_product:
                out['product'] = canonical_product
            return out

        # CAS 2: Mapping présent
        # Leclerc (URL directe)
        if ('leclerc' in urls_map) and (wanted is None or 'leclerc' in wanted):
            url = urls_map['leclerc']
            try:
                try:
                    from .stores import leclerc as _leclerc_mod
                    lr = _leclerc_mod.scrape_minimal(url, debug=False, headful=True)
                except Exception:
                    lr = _scrape_leclerc_minimal(url, debug=False, headful=True)
                results.append({'store': 'leclerc', 'ok': lr.get('ok'), 'price': lr.get('price'), 'ean': lr.get('ean'), 'desc': lr.get('desc'), 'url': url, 'bot': lr.get('bot_protection', False)})
            except Exception as e:
                results.append({'store': 'leclerc', 'ok': False, 'error': str(e)})

        # Carrefour (multi slugs)
        if (wanted is None or 'carrefour' in wanted):
            if carrefour_store and ',' in carrefour_store:
                for slug in [s.strip() for s in carrefour_store.split(',') if s.strip()]:
                    _append_carrefour(slug)
            else:
                _append_carrefour(carrefour_store)

        # Intermarché
        if (wanted is None or 'intermarche' in wanted):
            _append_intermarche()

        out = {"ok": True, "ean": ean, "results": results}
        if canonical_product:
            out['product'] = canonical_product
        return out
                browser = p.chromium.launch(headless=True, args=[
                    "--lang=fr-FR,fr",
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ])
            except Exception:
                return {"ok": False, "code": None, "final_url": None, "html": "", "bot_protection": False}

        # Context + page
        try:
            ctx = browser.contexts[0] if browser.contexts else browser.new_context(
                locale="fr-FR",
                user_agent=UA,
                extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"},
            )
        except Exception:
            ctx = browser.new_context(
                locale="fr-FR",
                user_agent=UA,
                extra_http_headers={"Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"},
            )

        page = ctx.new_page()
        page.set_default_timeout(15000)

        # Warm-up on base domain (cookies) then navigate to target
        try:
            page.goto(base, wait_until="domcontentloaded")
            _accept_consent(page)
            page.wait_for_timeout(400)
        except Exception:
            pass

        page.goto(url, referer=base, wait_until="domcontentloaded")
        _accept_consent(page)

        # If on Carrefour search results, try to auto-click the best matching product
        try:
            cur_url = page.url or url
        except Exception:
            cur_url = url
        if autoclick and isinstance(cur_url, str) and ("carrefour.fr" in cur_url) and ("/s?" in cur_url or cur_url.endswith("/s")):
            try:
                _carrefour_autoclick_product(page, cur_url)
            except Exception:
                pass
                browser.close()
            except Exception:
                pass

        return result

def engine_playwright(url: str, store_root: str):
    UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'
    with sync_playwright() as p:
        browser = None
        mode = 'attach'
        try:
            # 1) Essayer de se brancher sur Chrome déjà ouvert (CDP)
            browser = p.chromium.connect_over_cdp('http://127.0.0.1:9222')
        except Exception:
            # 2) Fallback: lancer Chromium Playwright (headful)
            mode = 'launch'
            browser = p.chromium.launch(headless=True, args=[
                '--lang=fr-FR,fr',
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ])

        # Contexte
        try:
            ctx = browser.contexts[0] if browser.contexts else browser.new_context(
                locale='fr-FR',
                user_agent=UA,
                extra_http_headers={'Accept-Language': 'fr-FR,fr;q=0.9'},
            )
        except Exception:
            ctx = browser.new_context(
                locale='fr-FR',
                user_agent=UA,
                extra_http_headers={'Accept-Language': 'fr-FR,fr;q=0.9'},
            )

        page = ctx.new_page()
        page.set_default_timeout(15000)

        try:
            page.goto(store_root, wait_until='domcontentloaded')
            page.wait_for_timeout(800)
            _accept_consent(page)
        except Exception:
            pass

        page.goto(url, referer=store_root, wait_until='domcontentloaded')
        _accept_consent(page)
        # Respecter MAXI_NOPUZZLE (ne pas bloquer inutilement)
        try:
            import os as _os
            _no_puz = (_os.environ.get('MAXI_NOPUZZLE','').lower() in ('1','true','yes'))
        except Exception:
            _no_puz = False
        if not _no_puz:
            try:
                _wait_if_bot_puzzle(page, timeout_ms=60000)
            except Exception:
                pass

        # Scrolls + idle pour laisser charger les prix dynamiques
        for _ in range(6):
            try:
                page.mouse.wheel(0, 1200)
            except Exception:
                pass
            page.wait_for_timeout(600)
        # Carrefour: s'il n'y a pas encore de prix, tenter d'exposer les options d'achat
        try:
            if 'carrefour.fr' in (urlparse(url).hostname or '').lower():
                _carrefour_make_price_visible(page, url)
        except Exception:
            pass
        try:
            page.wait_for_load_state('networkidle', timeout=5000)
        except Exception:
            pass

        host = (urlparse(url).hostname or '').lower()
        title = None; price = None
        unit_hint = {}

        # Plusieurs lectures du DOM
        for _ in range(4):
            try:
                # Quick re-vérification de barrière anti-bot
                try:
                    if is_bot_protection(page.content()):
                        _wait_if_bot_puzzle(page, timeout_ms=180000)
                except Exception:
                    pass
                html = page.content()
                res = extract_from_html_common(html, page.title(), host)
                if isinstance(res, tuple):
                    # Supporte 3 ou 4 retours
                    if len(res) >= 3:
                        t, pz, uh = res[0], res[1], res[2]
                        if pz is not None:
                            title, price = t, pz
                            unit_hint = uh
                            break
            except Exception:
                pass
            page.wait_for_timeout(800)

        # Fermer la page dans tous les cas pour éviter l'accumulation d'onglets
        try:
            page.close()
        except Exception:
            pass
        # Fermer le navigateur seulement si on l'a lancé nous‑mêmes
        if mode == 'launch':
            try:
                browser.close()
            except Exception:
                pass

        return title, price, unit_hint

def engine_selenium(url: str, store_root: str):
    opts = uc.ChromeOptions()
    opts.add_argument("--lang=fr-FR,fr")
    opts.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--headless=new")
    driver = uc.Chrome(options=opts)
    driver.set_page_load_timeout(60)
    try:
        driver.get(store_root)
        time.sleep(1.5)
        driver.get(url)
        deadline = time.time() + 25
        last_html = None
        host = (urlparse(url).hostname or '').lower()
        title = None; price = None
        unit_hint = {}
        while time.time() < deadline and price is None:
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            except Exception:
                pass
            time.sleep(0.6)
            html = driver.page_source
            if html != last_html:
                last_html = html
                res = extract_from_html_common(html, driver.title, host)
                if isinstance(res, tuple):
                    if len(res) >= 3:
                        t, pz, uh = res[0], res[1], res[2]
                        if pz is not None:
                            title = t; price = pz; unit_hint = uh; break
    finally:
        try:
            driver.quit()
        except Exception:
            pass

# ---------- Main ----------

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "missing url"}))
        return
    url = sys.argv[1].strip()
    host = (urlparse(url).hostname or '').lower()
    store_root = re.sub(r"^(https?://[^/]+/magasin-[^/]+/).*", r"\1", url) if "/magasin-" in url else re.sub(r"^(https?://[^/]+/).*", r"\1", url)
    if not store_root.endswith("/"): store_root += "/"

    title = None; price = None
    ean = None  # <-- Ajout ici

    # 1) HTTP direct (toujours)
    html = None
    debug_path = None
    bot_wall = False
    uhint = {}
    try:
        html = fetch_direct(url, store_root)
        if html and is_bot_protection(html):
            bot_wall = True
            debug_path = dump_debug(url, html)
        else:
            title, price, uhint, ean = extract_from_html_common(html, "", host)
    except Exception:
        title, price, uhint = (None, None, {})

    # Dump auto si echec, ou si MAXI_DUMP=1 (même si réussi)
    if html is not None:
        if price is None or os.environ.get("MAXI_DUMP") == "1":
            debug_path = dump_debug(url, html)

    # 2) Local: Playwright si demandé (--attach ou MAXI_CDP=1)
    attach = any(a == '--attach' for a in sys.argv[2:]) or os.environ.get('MAXI_CDP') == '1' or os.environ.get('MAXI_ATTACH') == '1'
    uhint_pw = {}
    if price is None and PW_OK and attach:
        try:
            # Prefer lightweight HTML capture over full scripting to avoid long waits/timeouts
            _no_puz = False
            try:
                _no_puz = (os.environ.get('MAXI_NOPUZZLE','').lower() in ('1','true','yes'))
            except Exception:
                _no_puz = False
            r = fetch_playwright_html(url, store_root, wait_puzzle=(not _no_puz), autoclick=True)
            if isinstance(r, dict) and r.get('html'):
                title, price, uhint_pw, ean = extract_from_html_common(r['html'], "", host)
            else:
                title, price, uhint_pw = (None, None, {})
        except Exception:
            title, price, uhint_pw = (None, None, {})

    # 3) Local: Selenium si demandé (MAXI_SELENIUM=1)
    uhint_se = {}
    if price is None and SEL_OK and os.environ.get('MAXI_SELENIUM') == '1':
        try:
            tpu = engine_selenium(url, store_root)
            if isinstance(tpu, tuple) and len(tpu) == 4:
                title, price, uhint_se, ean = tpu
            elif isinstance(tpu, tuple) and len(tpu) == 3:
                title, price, uhint_se = tpu
            else:
                title, price = tpu
                uhint_se = {}
        except Exception:
            title, price, uhint_se = (None, None, {})

    # --- Prix unitaires ---
    unit = {"per_liter": None, "liters": None, "per_kg": None, "kg": None, "per_dose": None, "doses": None}
    # Prepare hint holders for merging
    uhint = locals().get('uhint', {})
    uhint_pw = locals().get('uhint_pw', {})
    uhint_se = locals().get('uhint_se', {})
    try:
        txt = html_to_text(html) if isinstance(html, str) else ""
        title_hint = title or ""

        # Litres
        liters = parse_liters_from_text(title_hint) or parse_liters_from_text(txt)
        if liters:
            try:
                unit["liters"] = round(float(liters), 3)
            except Exception:
                unit["liters"] = liters
        pll = extract_unit_price_per_liter(html) if html else None
        if liters and (pll is not None):
            unit["per_liter"] = round(pll, 2)
        elif price is not None and liters:
            try:
                unit["per_liter"] = round(price / float(liters), 2)
            except Exception:
                pass
        else:
            # Pas de volume => ignorer tout signal supposé €/L pour éviter les faux positifs (ex: "/lavage")
            unit["per_liter"] = None

        # Kilogrammes
        kg = None
        kg_vals = parse_weights_kg_all(title_hint) if title_hint else []
        if not kg_vals:
            kg_vals = parse_weights_kg_all(txt)
        # Carrefour: tenter une lecture dédiée du poids pack si non détecté
        try:
            if ('carrefour.fr' in (host or '')):
                from stores import carrefour as cf
                wkg2 = cf.extract_pack_weight_kg(html)
                if wkg2 and wkg2 > 0:
                    kg = wkg2
        except Exception:
            pass

        if kg_vals:
            kg = max(kg_vals)  # éviter les mini-mentions (ex: 309 g vs 346 g)
        else:
            kg = parse_weight_kg_from_text(title_hint) or parse_weight_kg_from_text(txt)

        if kg:
            try:
                unit["kg"] = round(float(kg), 3)
            except Exception:
                unit["kg"] = kg

        ppk = extract_unit_price_per_kg(html) if html else None
        if ppk is not None:
            unit["per_kg"] = round(ppk, 2)
        elif price is not None and kg:
            try:
                unit["per_kg"] = round(price / float(kg), 2)
            except Exception:
                pass

        # Doses / capsules
        doses = parse_count_from_text(title_hint) or parse_count_from_text(txt)
        if doses:
            try:
                unit["doses"] = int(doses)
            except Exception:
                unit["doses"] = doses
        ppd = extract_unit_price_per_dose(html) if html else None
        if ppd is not None:
            unit["per_dose"] = round(ppd, 2)
        elif price is not None and unit.get("doses"):
            try:
                unit["per_dose"] = round(price / float(unit["doses"]), 2)
            except Exception:
                pass
        # Inférer une quantité manquante si on a prix + unitaire
        try:
            if price is not None:
                if unit.get("per_kg") and not unit.get("kg"):
                    pk = float(unit["per_kg"]) or 0.0
                    if pk > 0:
                        unit["kg"] = round(float(price)/pk, 3)
                if unit.get("per_liter") and not unit.get("liters"):
                    pl = float(unit["per_liter"]) or 0.0
                    if pl > 0:
                        unit["liters"] = round(float(price)/pl, 3)
                if unit.get("per_dose") and not unit.get("doses"):
                    pd = float(unit["per_dose"]) or 0.0
                    if pd > 0:
                        unit["doses"] = int(round(float(price)/pd))
        except Exception:
            pass
        # Merge unit hints from extractor (direct/PW/SE)
        for src in (locals().get('uhint', {}), locals().get('uhint_pw', {}), locals().get('uhint_se', {})):
            if not isinstance(src, dict):
                continue
            for k, v in src.items():
                if v is None or unit.get(k) not in (None, 0):
                    continue
                unit[k] = v

        # Final consistency: derive per-unit from total price if quantity is known
        try:
            if unit.get("per_kg") in (None, 0) and unit.get("kg") and price is not None:
                unit["per_kg"] = round(float(price) / float(unit["kg"]), 2)
            if unit.get("per_liter") in (None, 0) and unit.get("liters") and price is not None:
                unit["per_liter"] = round(float(price) / float(unit["liters"]), 2)
            if unit.get("per_dose") in (None, 0) and unit.get("doses") and price is not None:
                unit["per_dose"] = round(float(price) / float(unit["doses"]), 3)
        except Exception:
            pass
    except Exception:
        pass

    if price is None:
        out = {"ok": False, "error": "price not found"}
        if 'debug_path' in locals() and debug_path:
            out["debug_dump"] = debug_path
        if ean:
            out["ean"] = ean
        print(json.dumps(out))
        return

    out = {"ok": True, "url": url, "title": title or "", "price": price, "currency": "EUR", "unit": unit}
    if ean:
        out["ean"] = ean
    if 'debug_path' in locals() and debug_path:
        out["debug_dump"] = debug_path
    print(json.dumps(out, ensure_ascii=False))

# ---------- Lightweight HTTP worker ----------

def _run_self(url: str, attach: bool = False, nopuzzle: bool = True) -> dict:
    """Invoke this script as a subprocess to reuse main() logic and capture JSON.
    If attach=True, allow Playwright attach but still disable long puzzle waits.
    """
    try:
        cmd = [sys.executable, os.path.abspath(__file__), url]
        if attach:
            cmd.append('--attach')
        env = os.environ.copy()
        env.setdefault('MAXI_CDP', '1' if attach else '0')
        env.setdefault('MAXI_ATTACH', '1' if attach else '0')
        # Honour requested puzzle behavior
        env['MAXI_NOPUZZLE'] = '1' if nopuzzle else '0'
        env.setdefault('PYTHONUNBUFFERED', '1')
        # Allow more time when attach=True to let a human solve anti-bot puzzles (e.g. Carrefour)
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=180 if attach else 45)
        out = p.stdout.strip()
        return json.loads(out) if out else {"ok": False, "error": "empty_output", "stderr": p.stderr}
    except Exception as e:
        return {"ok": False, "error": f"subprocess_error: {e}"}

class _Handler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, payload: dict):
        data = json.dumps(payload).encode('utf-8')
        try:
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                # Client closed the connection; ignore silently
                pass
        except Exception:
            # As a last resort, avoid crashing the handler
            try:
                self.close_connection = True
            except Exception:
                pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        try:
            path = self.path.split('?', 1)[0]
            if path == '/health':
                return self._send_json(200, {"ok": True})
            if path == '/scrape':
                qs = parse_qs(urlsplit(self.path).query)
                url = (qs.get('url') or [''])[0]
                attach = ((qs.get('attach') or ['0'])[0]).lower() in ('1','true','yes')
                nopuzzle = ((qs.get('nopuzzle') or ['1'])[0]).lower() in ('1','true','yes')
                if not url:
                    return self._send_json(400, {"ok": False, "error": "missing url"})
                res = _run_self(url, attach=attach, nopuzzle=nopuzzle)
                return self._send_json(200, res)
            if path == '/carrefour_check':
                qs = parse_qs(urlsplit(self.path).query)
                raw = (qs.get('slugs') or [''])[0]
                if not raw:
                    return self._send_json(400, {"ok": False, "error": "missing slugs"})
                slugs = [s.strip() for s in raw.split(',') if s.strip()]
                res = _check_carrefour_slugs(slugs)
                return self._send_json(200, {"ok": True, "results": res})
            if path == '/fetch':
                qs = parse_qs(urlsplit(self.path).query)
                url = (qs.get('url') or [''])[0].strip()
                referer = (qs.get('referer') or [''])[0].strip() or re.sub(r'^(https?://[^/]+/).*', r'\1', url)
                attach = ((qs.get('attach') or ['0'])[0]).lower() in ('1','true','yes')
                nopuzzle = ((qs.get('nopuzzle') or ['0'])[0]).lower() in ('1','true','yes')
                autoclick = ((qs.get('autoclick') or ['1'])[0]).lower() in ('1','true','yes')
                wait_puzzle = not nopuzzle
                if not url:
                    return self._send_json(400, {"ok": False, "error": "missing url"})

                res = {"ok": False, "code": None, "final_url": None, "html": "", "bot_protection": False}
                if attach:
                    try:
                        r = fetch_playwright_html(url, referer, wait_puzzle=wait_puzzle, autoclick=autoclick)
                        if isinstance(r, dict):
                            res.update(r)
                    except Exception:
                        pass

                # fallback or if still blocked
                if (not res.get("ok")) or (not res.get("html")):
                    code, final_url, html = fetch_raw_with_meta(url, referer)
                    res.update({
                        "ok": True,
                        "code": code,
                        "final_url": final_url,
                        "html": html,
                        "bot_protection": is_bot_protection(html) if isinstance(html, str) else False,
                    })

                return self._send_json(200, res)
            if path == '/compare':
                qs = parse_qs(urlsplit(self.path).query)
                ean = (qs.get('ean') or [''])[0].strip()
                attach = ((qs.get('attach') or ['1'])[0]).lower() in ('1','true','yes')
                nopuzzle = ((qs.get('nopuzzle') or ['1'])[0]).lower() in ('1','true','yes')
                debug = ((qs.get('debug') or ['0'])[0]).lower() in ('1','true','yes')
                stores = (qs.get('stores') or [''])[0]
                stores = [s.strip() for s in stores.split(',')] if stores else None
                # Nouveaux paramètres spécifiques Carrefour (alignés avec POST)
                carrefour_store = (qs.get('carrefour_store') or [''])[0].strip() or None
                carrefour_product = (qs.get('carrefour_product') or [''])[0].strip() or None
                carrefour_store_url = (qs.get('carrefour_store_url') or [''])[0].strip() or None
                if not ean:
                    return self._send_json(400, {"ok": False, "error": "missing ean"})
                res = _compare_ean(
                    ean,
                    attach=attach,
                    nopuzzle=nopuzzle,
                    debug=debug,
                    stores=stores,
                    carrefour_store=carrefour_store,
                    carrefour_product=carrefour_product,
                    carrefour_store_url=carrefour_store_url
                )
                return self._send_json(200, res)
            return self._send_json(404, {"ok": False, "error": "not found"})
        except Exception as e:
            return self._send_json(500, {"ok": False, "error": str(e)})

    def do_POST(self):
        try:
            path = self.path.split('?', 1)[0]
            n = int(self.headers.get('Content-Length') or '0')
            body = self.rfile.read(n) if n else b''
            try:
                payload = json.loads(body.decode('utf-8') or '{}')
            except Exception:
                payload = {}

            if path == '/scrape':
                url = (payload.get('url') or '').strip()
                attach = str(payload.get('attach') or '0').lower() in ('1','true','yes')
                nopuzzle = str(payload.get('nopuzzle') or '1').lower() in ('1','true','yes')
                if not url:
                    return self._send_json(400, {"ok": False, "error": "missing url"})
                res = _run_self(url, attach=attach, nopuzzle=nopuzzle)
                return self._send_json(200, res)

            if path == '/fetch':
                url = (payload.get('url') or '').strip()
                referer = (payload.get('referer') or '').strip() or re.sub(r'^(https?://[^/]+/).*', r'\1', url)
                attach = str(payload.get('attach') or '0').lower() in ('1','true','yes')
                nopuzzle = str(payload.get('nopuzzle') or '0').lower() in ('1','true','yes')
                autoclick = str(payload.get('autoclick') or '1').lower() in ('1','true','yes')
                wait_puzzle = not nopuzzle
                if not url:
                    return self._send_json(400, {"ok": False, "error": "missing url"})

                res = {"ok": False, "code": None, "final_url": None, "html": "", "bot_protection": False}
                if attach:
                    try:
                        r = fetch_playwright_html(url, referer, wait_puzzle=wait_puzzle, autoclick=autoclick)
                        if isinstance(r, dict):
                            res.update(r)
                    except Exception:
                        pass

                if (not res.get('ok')) or (not res.get('html')):
                    code, final_url, html = fetch_raw_with_meta(url, referer)
                    res.update({
                        "ok": True,
                        "code": code,
                        "final_url": final_url,
                        "html": html,
                        "bot_protection": is_bot_protection(html) if isinstance(html, str) else False,
                    })

                return self._send_json(200, res)

            if path == '/compare':
                ean = (payload.get('ean') or '').strip()
                attach = str(payload.get('attach') or '1').lower() in ('1','true','yes')
                nopuzzle = str(payload.get('nopuzzle') or '1').lower() in ('1','true','yes')
                debug = str(payload.get('debug') or '0').lower() in ('1','true','yes')
                stores = payload.get('stores') or None
                if isinstance(stores, str):
                    stores = [s.strip() for s in stores.split(',')] if stores.strip() else None
                carrefour_store = (payload.get('carrefour_store') or '').strip() or None
                carrefour_product = (payload.get('carrefour_product') or '').strip() or None
                carrefour_store_url = (payload.get('carrefour_store_url') or '').strip() or None
                if not ean:
                    return self._send_json(400, {"ok": False, "error": "missing ean"})
                res = _compare_ean(ean, attach=attach, nopuzzle=nopuzzle, debug=debug, stores=stores, carrefour_store=carrefour_store, carrefour_product=carrefour_product, carrefour_store_url=carrefour_store_url)
                return self._send_json(200, res)

            return self._send_json(404, {"ok": False, "error": "not found"})
        except Exception as e:
            return self._send_json(500, {"ok": False, "error": str(e)})

# --- Fin propre du fichier ---
if __name__ == "__main__":
    if "--serve" in sys.argv:
        i = sys.argv.index("--serve")
        bind = sys.argv[i + 1] if i + 1 < len(sys.argv) else "127.0.0.1:5001"
        run_server(bind)
    else:
        main()