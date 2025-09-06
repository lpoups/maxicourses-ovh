#!/usr/bin/env python3
# Maxicourses — Scraper multi-enseignes (serveur + local)
# Serveur OVH: HTTP direct (urllib), aucune dépendance obligatoire.
# Local: Playwright CDP (--attach ou MAXI_CDP=1) et/ou Selenium undetected si dispo.
# Extraction: JSON-LD, scripts, HTML visible + conversions €/L, €/kg, €/dose.
# Debug: si le prix est introuvable, on sauvegarde automatiquement l'HTML dans /api/debug.
#        si MAXI_DUMP=1 est défini, on sauvegarde aussi quand un prix est trouvé.

import sys, json, re, time, os, html as htmllib, gzip, io
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPCookieProcessor
from http.cookiejar import CookieJar

# ---------- Optional deps ----------
BeautifulSoup = None
try:
    from bs4 import BeautifulSoup as _BS
    BeautifulSoup = _BS
except Exception:
    BeautifulSoup = None

PW_OK = True
try:
    from playwright.sync_api import sync_playwright
except Exception:
    PW_OK = False

SEL_OK = True
try:
    import undetected_chromedriver as uc
    from selenium import webdriver
except Exception:
    SEL_OK = False

# ---------- Helpers ----------

def norm_price(s: str):
    s = re.sub(r"[^\d,\.]", "", s or "")
    if s.count(".") > 1:
        s = re.sub(r"\.(?=.*\.)", "", s)
    s = s.replace(",", ".")
    try:
        return round(float(s), 2)
    except Exception:
        return None

def html_to_text(html: str) -> str:
    txt = re.sub(r"<script[\\s\\S]*?<\\/script>", " ", html or "", flags=re.I)
    txt = re.sub(r"<style[\\s\\S]*?<\\/style>", " ", txt, flags=re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = htmllib.unescape(txt)
    txt = re.sub(r"\\s+", " ", txt).strip()
    return txt

def soup_or_text(html: str):
    if BeautifulSoup is not None:
        try:
            return BeautifulSoup(html, "lxml"), None
        except Exception:
            pass
    return None, html_to_text(html)

# ---------- Extraction ----------

def price_from_jsonld(html: str):
    """Extract price via JSON-LD Product schema. Robust to missing lxml/bs4.
    Strategy:
      1) If BeautifulSoup is available, try lxml else html.parser.
      2) Always ALSO add regex-captured <script type="application/ld+json"> blocks as fallback.
      3) Walk any parsed JSON (dict/list) to find a Product.offers.price.
    """
    try:
        blocks = []
        soup = None
        if BeautifulSoup is not None:
            # Try lxml first; if not present, fallback to built-in parser.
            try:
                soup = BeautifulSoup(html, "lxml")
            except Exception:
                try:
                    soup = BeautifulSoup(html, "html.parser")
                except Exception:
                    soup = None
            if soup is not None:
                for tag in soup.select('script[type="application/ld+json"]'):
                    blocks.append(tag.string or tag.text or "")

        # Regex fallback is ALWAYS attempted (even if bs4 worked) — increases robustness.
        for m in re.finditer(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>([\s\S]*?)</script>', html or "", re.I):
            blocks.append(m.group(1))

        import json as _json
        for raw in blocks:
            if not raw:
                continue
            txt = raw.strip()
            # Tolerate dangling commas
            txt = re.sub(r',\s*([}\]])', r'\1', txt)
            try:
                data = _json.loads(txt)
            except Exception:
                continue

            stack = [data]
            while stack:
                cur = stack.pop()
                if isinstance(cur, dict):
                    if cur.get("@type") == "Product":
                        name = (cur.get("name") or "").strip()
                        offers = cur.get("offers")

                        def _price_from_offers(offers):
                            if isinstance(offers, dict):
                                return offers.get("price") or (offers.get("priceSpecification") or {}).get("price")
                            if isinstance(offers, list):
                                for o in offers:
                                    if isinstance(o, dict):
                                        p = o.get("price") or (o.get("priceSpecification") or {}).get("price")
                                        if p is not None:
                                            return p
                            return None

                        p = _price_from_offers(offers)
                        if p is not None:
                            return name, norm_price(str(p))

                    # continue walking
                    for v in cur.values():
                        if isinstance(v, (dict, list)):
                            stack.append(v)
                elif isinstance(cur, list):
                    for v in cur:
                        if isinstance(v, (dict, list)):
                            stack.append(v)
    except Exception:
        pass
    return None, None

def price_from_scripts(html: str):
    best = None
    # prix en centimes
    for m in re.findall(r'(?i)(?:priceInCents|sellingPriceInCents)\\\"?\\s*:\\s*(\\d{2,7})', html or ""):
        try:
            v = round(int(m) / 100.0, 2)
            if 0.2 <= v <= 200 and (best is None or v < best):
                best = v
        except Exception:
            pass
    # "price": "2,39" ou 2.39
    for m in re.findall(r'\\\"price\\\"\\s*:\\s*\\\"?(\\d+(?:[.,]\\d{1,2}))\\\"?', html or ""):
        v = norm_price(m)
        if v and 0.2 <= v <= 200 and (best is None or v < best):
            best = v
    # "formattedPrice": "2,39 €"
    for m in re.findall(r'\\\"formattedPrice\\\"\\s*:\\s*\\\"([^\\\"]*[0-9][.,][0-9]{1,2})\\\"', html or ""):
        v = norm_price(m)
        if v and 0.2 <= v <= 200 and (best is None or v < best):
            best = v
    if best is not None:
        return None, best
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
        for mm in re.finditer(r"<meta[^>]*itemprop=\\\"price\\\"[^>]*content=\\\"([^\\\"]+)\\\"[^>]*>", html or "", re.I):
            v = norm_price(mm.group(1))
            if v and 0.2 <= v <= 200:
                candidates.append(v)
        text = html_to_text(html)
    for a, b in re.findall(r"(?:([0-9]+[.,][0-9]{1,2})\\s*(?:€|\\u20AC)|(?:€|\\u20AC)\\s*([0-9]+[.,][0-9]{1,2}))", text or ""):
        s = a or b
        v = norm_price(s)
        if v and 0.2 <= v <= 200:
            candidates.append(v)
    if candidates:
        return title, min(candidates)
    return None, None

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
    for rgx in [r"(\\d+[.,]\\d{1,2})\\s*€\\s*\\/\\s*[lL]", r"(\\d+[.,]\\d{1,2})\\s*€\\s*par\\s*[lL]", r"(\\d+[.,]\\d{1,2})\\s*€\\/\\s*[lL]"]:
        m = re.search(rgx, txt or "")
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

def extract_unit_price_per_kg(html: str):
    soup, txt = soup_or_text(html)
    if soup is not None:
        txt = soup.get_text(" ", strip=True)
    for rgx in [r"(\\d+[.,]\\d{1,2})\\s*€\\s*\\/\\s*kg", r"(\\d+[.,]\\d{1,2})\\s*€\\/kg", r"(\\d+[.,]\\d{1,2})\\s*€\\s*par\\s*kg"]:
        m = re.search(rgx, txt or "", re.I)
        if m:
            v = norm_price(m.group(1))
            if v and 0.2 <= v <= 999:
                return v
    return None

def parse_count_from_text(text: str):
    m = re.search(r"(\\d{1,3})\\s*(?:caps|dosettes|doses|pods)\\b", text or "", re.I)
    return int(m.group(1)) if m else None

def extract_unit_price_per_dose(html: str):
    soup, txt = soup_or_text(html)
    if soup is not None:
        txt = soup.get_text(" ", strip=True)
    for rgx in [r"(\\d+[.,]\\d{1,2})\\s*€\\s*\\/\\s*(?:dose|lavage|cap(?:s)?)", r"(\\d+[.,]\\d{1,2})\\s*€\\s*par\\s*(?:dose|lavage|cap(?:s)?)"]:
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
    for m in re.finditer(r"(\\d{1,3}(?:[.,]\\d{1,2}))\\s*€", txt2 or ""):
        end = m.end(); tail = (txt2[end:end+12] or '').lower()
        if '/l' in tail or 'par l' in tail:
            continue
        v = norm_price(m.group(1))
        if v and 0.2 <= v <= 200:
            return v
    return None

def extract_from_html_common(html: str, title_hint: str, host: str):
    title, price = price_from_jsonld(html)
    if price is None:
        title, price = price_from_scripts(html)
    if price is None:
        title, price = price_from_html(html)

    unit_pl = extract_unit_price_per_liter(html)
    if unit_pl is not None:
        lit = parse_liters_from_text(title_hint or title or "")
        if lit is None:
            lit = parse_liters_from_text(html_to_text(html)[:6000])
        if lit and lit > 0:
            computed = round(unit_pl * lit, 2)
            if price is None or abs(price - unit_pl) < 0.06 or price < unit_pl:
                price = computed

    unit_kg = extract_unit_price_per_kg(html)
    if unit_kg is not None:
        kg = parse_weight_kg_from_text(title_hint or title or "")
        if kg is None:
            kg = parse_weight_kg_from_text(html_to_text(html)[:6000])
        if kg and kg > 0:
            computed = round(unit_kg * kg, 2)
            if price is None or abs(price - unit_kg) < 0.1 or price < unit_kg:
                price = computed

    unit_dose = extract_unit_price_per_dose(html)
    if unit_dose is not None:
        n = parse_count_from_text(title_hint or title or "")
        if n is None:
            n = parse_count_from_text(html_to_text(html)[:6000])
        if n and n > 0:
            computed = round(unit_dose * n, 2)
            if price is None or price < unit_dose or abs(price - unit_dose) < 0.1:
                price = computed

    if 'intermarche.com' in host:
        p_first = first_price_before_marker(html)
        if p_first and price and price > p_first * 1.5:
            price = p_first

    return title, price

# ---------- Fetch + debug dump ----------

def fetch_direct(url: str, referer: str):
    cj = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cj))
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate',
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
        low = (html or "").lower()
    except Exception:
        return False
    markers = [
        "captcha-delivery.com",
        "enable javascript",
        "please enable javascript",
        "pardon the interruption",
        "access denied",
        "request unsuccessful",
        "are you a human",
        "distil_r_captcha",
        "akamai",
        "bot detection",
        "cf-chl-bypass",
        "cloudflare",
        "unusual traffic",
        "one more step",
        "/cdn-cgi/challenge-platform",
    ]
    return any(m in low for m in markers)

# ---------- Local engines (optionnels) ----------

def engine_playwright(url: str, store_root: str):
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context(locale="fr-FR")
        page = ctx.new_page()
        page.set_default_timeout(12000)
        page.goto(store_root, wait_until="domcontentloaded")
        page.goto(url, referer=store_root, wait_until="domcontentloaded")
        for _ in range(5):
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            page.wait_for_timeout(600)
        html = page.content()
        host = (urlparse(url).hostname or '').lower()
        title, price = extract_from_html_common(html, page.title(), host)
        if price is None:
            page.wait_for_timeout(800)
            html = page.content()
            title, price = extract_from_html_common(html, page.title(), host)
        return title, price

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
        while time.time() < deadline and price is None:
            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            except Exception:
                pass
            time.sleep(0.6)
            html = driver.page_source
            if html != last_html:
                last_html = html
                t, pz = extract_from_html_common(html, driver.title, host)
                if pz is not None:
                    title = t; price = pz; break
        return title, price
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
    store_root = re.sub(r"^(https?://[^/]+/magasin-[^/]+/).*", r"\\1", url) if "/magasin-" in url else re.sub(r"^(https?://[^/]+/).*", r"\\1", url)
    if not store_root.endswith("/"): store_root += "/"

    title = None; price = None

    # 1) HTTP direct (toujours)
    html = None
    debug_path = None
    try:
        html = fetch_direct(url, store_root)
        # Détection anti-bot: on sort tôt avec un message explicite
        if html and is_bot_protection(html):
            debug_path = dump_debug(url, html)
            out = {"ok": False, "error": "bot_protection"}
            if debug_path:
                out["debug_dump"] = debug_path
            print(json.dumps(out))
            return
        title, price = extract_from_html_common(html, "", host)
    except Exception:
        title, price = (None, None)

    # Dump auto si echec, ou si MAXI_DUMP=1 (même si réussi)
    if html is not None:
        if price is None or os.environ.get("MAXI_DUMP") == "1":
            debug_path = dump_debug(url, html)

    # 2) Local: Playwright si demandé (--attach ou MAXI_CDP=1)
    attach = any(a == '--attach' for a in sys.argv[2:]) or os.environ.get('MAXI_CDP') == '1' or os.environ.get('MAXI_ATTACH') == '1'
    if price is None and PW_OK and attach:
        try:
            title, price = engine_playwright(url, store_root)
        except Exception:
            title, price = (None, None)

    # 3) Local: Selenium si demandé (MAXI_SELENIUM=1)
    if price is None and SEL_OK and os.environ.get('MAXI_SELENIUM') == '1':
        try:
            title, price = engine_selenium(url, store_root)
        except Exception:
            title, price = (None, None)

    if price is None:
        out = {"ok": False, "error": "price not found"}
        if 'debug_path' in locals() and debug_path:
            out["debug_dump"] = debug_path
        print(json.dumps(out))
        return

    out = {"ok": True, "url": url, "title": title or "", "price": price, "currency": "EUR"}
    if 'debug_path' in locals() and debug_path:
        out["debug_dump"] = debug_path
    print(json.dumps(out, ensure_ascii=False))

if __name__ == '__main__':
    main()