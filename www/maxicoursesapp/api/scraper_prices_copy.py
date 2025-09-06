#!/usr/bin/env python3
# Maxicourses — Scraper multi-enseignes
# Mode prioritaire: Playwright CDP (Chrome --remote-debugging-port=9222)
# Fallback: undetected-chromedriver (selenium)

import sys, json, re, time, os
from urllib.parse import urlparse
from bs4 import BeautifulSoup

# --- Try optional engines ---
PW_OK = True
try:
    from playwright.sync_api import sync_playwright
except Exception:
    PW_OK = False

SEL_OK = True
try:
    import undetected_chromedriver as uc
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
except Exception:
    SEL_OK = False

# ----------------- helpers extraction -----------------

def norm_price(s: str):
    s = re.sub(r"[^\d,\.]", "", s)
    if s.count(".") > 1:
        s = re.sub(r"\.(?=.*\.)", "", s)
    s = s.replace(",", ".")
    try:
        return round(float(s), 2)
    except Exception:
        return None


def price_from_jsonld(html: str):
    try:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup.select('script[type="application/ld+json"]'):
            txt = tag.text.strip()
            if '"@type"' not in txt or '"Product"' not in txt:
                continue
            txt2 = re.sub(r",\s*([}\]])", r"\1", txt)
            import json as _json
            data = _json.loads(txt2)
            stack = [data]
            while stack:
                cur = stack.pop()
                if isinstance(cur, dict):
                    if cur.get("@type") == "Product":
                        name = cur.get("name")
                        offers = cur.get("offers")
                        if isinstance(offers, dict):
                            p = offers.get("price") or offers.get("priceSpecification", {}).get("price")
                            if p: return name, norm_price(str(p))
                        if isinstance(offers, list):
                            for o in offers:
                                p = o.get("price") or o.get("priceSpecification", {}).get("price")
                                if p: return name, norm_price(str(p))
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
    # on prend le plus petit prix plausible pour éviter d’attraper des prix de packs énormes
    best = None
    for m in re.findall(r"(?i)(?:priceInCents|sellingPriceInCents)\"?\s*:\s*(\d{2,7})", html):
        try:
            cents = int(m)
            v = round(cents / 100.0, 2)
            if 0.2 <= v <= 200 and (best is None or v < best):
                best = v
        except Exception:
            pass
    for m in re.findall(r"\"price\"\s*:\s*\"?(\d+[.,]\d{2})\"?", html):
        v = norm_price(m)
        if v and 0.2 <= v <= 200 and (best is None or v < best):
            best = v
    for m in re.findall(r"\"formattedPrice\"\s*:\s*\"([^\"]*[0-9][.,][0-9]{2})\"", html):
        v = norm_price(m)
        if v and 0.2 <= v <= 200 and (best is None or v < best):
            best = v
    if best is not None:
        return None, best
    return None, None


def price_from_html(html: str):
    soup = BeautifulSoup(html, "lxml")
    candidates = []
    for meta in soup.select('meta[itemprop="price"]'):
        if meta and meta.get("content"):
            v = norm_price(meta["content"])
            if v and 0.2 <= v <= 200:
                candidates.append(v)
    for el in soup.select('span[class*="price"], div[class*="price"] span, span[class*="BasePrice"], span[class*="base-price"], [data-price]'):
        txt = (el.get("data-price") or el.get_text(" ").strip())
        v = norm_price(str(txt))
        if v and 0.2 <= v <= 200:
            candidates.append(v)
    text = soup.get_text(" ", strip=True)
    for a,b in re.findall(r"(?:([0-9]+[.,][0-9]{2})\s*(?:€|\u20AC)|(?:€|\u20AC)\s*([0-9]+[.,][0-9]{2}))", text):
        s = a or b
        v = norm_price(s)
        if v and 0.2 <= v <= 200:
            candidates.append(v)
    if candidates:
        title = soup.title.text.strip() if soup.title else None
        return title, min(candidates)
    return None, None


def parse_liters_from_text(text: str):
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:l|L)\b", text)
    if m:
        try:
            return float(m.group(1).replace(',', '.'))
        except Exception:
            return None
    return None


def extract_unit_price_per_liter(html: str):
    try:
        soup = BeautifulSoup(html, "lxml"); text = soup.get_text(" ", strip=True)
    except Exception:
        text = html
    for rgx in [
        r"(\d+[.,]\d{2})\s*€\s*/\s*[lL]",
        r"(\d+[.,]\d{2})\s*€\s*par\s*[lL]",
        r"(\d+[.,]\d{2})\s*€/\s*[lL]",
    ]:
        m = re.search(rgx, text)
        if m:
            v = norm_price(m.group(1))
            if v and 0.2 <= v <= 200:
                return v
    return None


def parse_weight_kg_from_text(text: str):
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|g)\b", text, re.I)
    if not m:
        return None
    val = float(m.group(1).replace(',', '.'))
    return val if m.group(2).lower() == 'kg' else val / 1000.0


def extract_unit_price_per_kg(html: str):
    try:
        soup = BeautifulSoup(html, "lxml"); txt = soup.get_text(" ", strip=True)
    except Exception:
        txt = html
    for rgx in [
        r"(\d+[.,]\d{2})\s*€\s*/\s*kg",
        r"(\d+[.,]\d{2})\s*€/kg",
        r"(\d+[.,]\d{2})\s*€\s*par\s*kg",
    ]:
        m = re.search(rgx, txt, re.I)
        if m:
            v = norm_price(m.group(1))
            if v and 0.2 <= v <= 999:
                return v
    return None


def parse_count_from_text(text: str):
    m = re.search(r"(\d{1,3})\s*(?:caps|dosettes|doses|pods)\b", text, re.I)
    return int(m.group(1)) if m else None


def extract_unit_price_per_dose(html: str):
    try:
        soup = BeautifulSoup(html, "lxml"); txt = soup.get_text(" ", strip=True)
    except Exception:
        txt = html
    for rgx in [
        r"(\d+[.,]\d{2})\s*€\s*/\s*(?:dose|lavage|cap(?:s)?)",
        r"(\d+[.,]\d{2})\s*€\s*par\s*(?:dose|lavage|cap(?:s)?)",
    ]:
        m = re.search(rgx, txt, re.I)
        if m:
            v = norm_price(m.group(1))
            if v and 0.01 <= v <= 10:
                return v
    return None


def first_price_before_marker(html: str):
    try:
        soup = BeautifulSoup(html, "lxml"); txt = soup.get_text(" ", strip=True)
    except Exception:
        txt = html
    lower = txt.lower(); cut = len(txt)
    for t in ['vous aimerez aussi', 'produits similaires', 'ils achètent aussi', 'vous pourriez aussi aimer']:
        i = lower.find(t)
        if i != -1 and i < cut:
            cut = i
    txt = txt[:cut]
    for m in re.finditer(r"(\d{1,3}(?:[.,]\d{2}))\s*€", txt):
        end = m.end(); tail = txt[end:end+12].lower()
        if '/l' in tail or 'par l' in tail:
            continue
        v = norm_price(m.group(1))
        if v and 0.2 <= v <= 200:
            return v
    return None

# ----------------- engines -----------------

def extract_from_html_common(html: str, title_hint: str, host: str):
    title, price = price_from_jsonld(html)
    if price is None:
        title, price = price_from_scripts(html)
    if price is None:
        title, price = price_from_html(html)

    # Ajustements unités → prix pack
    # €/L → total
    unit_pl = extract_unit_price_per_liter(html)
    if unit_pl is not None:
        lit = parse_liters_from_text(title_hint or title or "")
        if lit is None:
            try:
                soup = BeautifulSoup(html, "lxml")
                lit = parse_liters_from_text(soup.get_text(" ", strip=True)[:6000])
            except Exception:
                pass
        if lit and lit > 0:
            computed = round(unit_pl * lit, 2)
            if price is None or abs(price - unit_pl) < 0.06 or price < unit_pl:
                price = computed

    # €/kg → total
    unit_kg = extract_unit_price_per_kg(html)
    if unit_kg is not None:
        kg = parse_weight_kg_from_text(title_hint or title or "")
        if kg is None:
            try:
                soup = BeautifulSoup(html, "lxml")
                kg = parse_weight_kg_from_text(soup.get_text(" ", strip=True)[:6000])
            except Exception:
                pass
        if kg and kg > 0:
            computed = round(unit_kg * kg, 2)
            if price is None or abs(price - unit_kg) < 0.1 or price < unit_kg:
                price = computed

    # €/dose → total
    unit_dose = extract_unit_price_per_dose(html)
    if unit_dose is not None:
        n = parse_count_from_text(title_hint or title or "")
        if n is None:
            try:
                soup = BeautifulSoup(html, "lxml")
                n = parse_count_from_text(soup.get_text(" ", strip=True)[:6000])
            except Exception:
                pass
        if n and n > 0:
            computed = round(unit_dose * n, 2)
            if price is None or price < unit_dose or abs(price - unit_dose) < 0.1:
                price = computed

    # Intermarché: éviter carrousels
    if 'intermarche.com' in host:
        p_first = first_price_before_marker(html)
        if p_first and price and price > p_first * 1.5:
            price = p_first

    return title, price


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

# ----------------- main -----------------

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "missing url"}))
        return
    url = sys.argv[1].strip()
    host = (urlparse(url).hostname or '').lower()
    store_root = re.sub(r"^(https?://[^/]+/magasin-[^/]+/).*", r"\1", url) if "/magasin-" in url else re.sub(r"^(https?://[^/]+/).*", r"\1", url)
    if not store_root.endswith("/"): store_root += "/"

    title = None; price = None
    attach = any(a == '--attach' for a in sys.argv[2:]) or os.environ.get('MAXI_ATTACH') == '1'

    try:
        if PW_OK and attach:
            title, price = engine_playwright(url, store_root)
        elif PW_OK:
            # tente CDP si Chrome 9222 ouvert, sinon passe au fallback
            try:
                title, price = engine_playwright(url, store_root)
            except Exception:
                title, price = (None, None)
        if price is None and SEL_OK:
            title, price = engine_selenium(url, store_root)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return

    if price is None:
        print(json.dumps({"ok": False, "error": "price not found"}))
        return

    print(json.dumps({"ok": True, "url": url, "title": title or "", "price": price, "currency": "EUR"}, ensure_ascii=False))


if __name__ == '__main__':
    main()