#!/usr/bin/env python3
# Maxicourses — Scraper multi-enseignes (BASE STABLE LOCALE)
# Mode: Playwright CDP attach (Chrome lancé avec --remote-debugging-port=9222)
# Zéro service tiers. Extraction HTML → prix TTC unitaire.

import sys, json, re, time, os, html as htmllib
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

# -------- Optional BeautifulSoup (si installé, sinon fallback regex) --------
BeautifulSoup = None
try:
    from bs4 import BeautifulSoup as _BS
    BeautifulSoup = _BS
except Exception:
    BeautifulSoup = None

# ----------------- helpers -----------------
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
    txt = re.sub(r"<script[\s\S]*?<\/script>", " ", html or "", flags=re.I)
    txt = re.sub(r"<style[\s\S]*?<\/style>", " ", txt, flags=re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = htmllib.unescape(txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt

def soup_or_text(html: str):
    if BeautifulSoup is not None:
        try:
            return BeautifulSoup(html, "lxml"), None
        except Exception:
            pass
    return None, html_to_text(html)

def maybe_dump(html: str, url: str, engine: str):
    """
    If MAXI_DUMP is set (any non-empty value), write the HTML to /api/debug.
    Directory is taken from MAXI_DUMP_DIR, else defaults to "<script_dir>/debug".
    """
    try:
        if not os.environ.get('MAXI_DUMP'):
            return
        base_dir = os.environ.get('MAXI_DUMP_DIR') or os.path.join(os.path.dirname(__file__), 'debug')
        os.makedirs(base_dir, exist_ok=True)
        host = (urlparse(url).hostname or 'nohost').replace(':', '-')
        ts = time.strftime('%Y%m%d-%H%M%S')
        fname = f"{host}-{ts}-{engine}.html"
        path = os.path.join(base_dir, fname)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html or '')
    except Exception:
        # never break scraping because of dump issues
        pass

# ----------------- extraction générique -----------------
def price_from_jsonld(html: str):
    try:
        blocks = []
        if BeautifulSoup is not None:
            soup = BeautifulSoup(html, "lxml")
            for tag in soup.select('script[type="application/ld+json"]'):
                blocks.append(tag.text or "")
        else:
            for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>([\s\S]*?)</script>', html, re.I):
                blocks.append(m.group(1))
        import json as _json
        for txt in blocks:
            txt2 = re.sub(r",\s*([}\]])", r"\1", txt.strip())
            try:
                data = _json.loads(txt2)
            except Exception:
                continue
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
    best = None
    for m in re.findall(r'(?i)(?:priceInCents|sellingPriceInCents)"?\s*:\s*(\d{2,7})', html or ""):
        try:
            v = round(int(m) / 100.0, 2)
            if 0.2 <= v <= 200 and (best is None or v < best):
                best = v
        except Exception:
            pass
    for m in re.findall(r'"price"\s*:\s*"?(\d+[.,]\d{2})"?', html or ""):
        v = norm_price(m)
        if v and 0.2 <= v <= 200 and (best is None or v < best):
            best = v
    for m in re.findall(r'"formattedPrice"\s*:\s*"([^"]*[0-9][.,][0-9]{2})"', html or ""):
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
            title = soup.title.text.strip()
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
        for mm in re.finditer(r'<meta[^>]*itemprop="price"[^>]*content="([^"]+)"[^>]*>', html or "", re.I):
            v = norm_price(mm.group(1))
            if v and 0.2 <= v <= 200:
                candidates.append(v)
        text = html_to_text(html)
    for a,b in re.findall(r'(?:([0-9]+[.,][0-9]{2})\s*(?:€|\u20AC)|(?:€|\u20AC)\s*([0-9]+[.,][0-9]{2}))', text or ""):
        s = a or b
        v = norm_price(s)
        if v and 0.2 <= v <= 200:
            candidates.append(v)
    if candidates:
        return title, min(candidates)
    return None, None

# -------- conversions €/L, €/kg, €/dose → prix total --------
def parse_liters_from_text(text: str):
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:l|L)\b", text or "")
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
    for rgx in [r"(\d+[.,]\d{2})\s*€\s*/\s*[lL]", r"(\d+[.,]\d{2})\s*€\s*par\s*[lL]", r"(\d+[.,]\d{2})\s*€/\s*[lL]"]:
        m = re.search(rgx, txt or "")
        if m:
            v = norm_price(m.group(1))
            if v and 0.2 <= v <= 200:
                return v
    return None

def parse_weight_kg_from_text(text: str):
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|g)\b", text or "", re.I)
    if not m:
        return None
    val = float(m.group(1).replace(',', '.'))
    return val if m.group(2).lower() == 'kg' else val / 1000.0

def extract_unit_price_per_kg(html: str):
    soup, txt = soup_or_text(html)
    if soup is not None:
        txt = soup.get_text(" ", strip=True)
    for rgx in [r"(\d+[.,]\d{2})\s*€\s*/\s*kg", r"(\d+[.,]\d{2})\s*€/kg", r"(\d+[.,]\d{2})\s*€\s*par\s*kg"]:
        m = re.search(rgx, txt or "", re.I)
        if m:
            v = norm_price(m.group(1))
            if v and 0.2 <= v <= 999:
                return v
    return None

def parse_count_from_text(text: str):
    m = re.search(r"(\d{1,3})\s*(?:caps|dosettes|doses|pods)\b", text or "", re.I)
    return int(m.group(1)) if m else None

def extract_unit_price_per_dose(html: str):
    soup, txt = soup_or_text(html)
    if soup is not None:
        txt = soup.get_text(" ", strip=True)
    for rgx in [r"(\d+[.,]\d{2})\s*€\s*/\s*(?:dose|lavage|cap(?:s)?)", r"(\d+[.,]\d{2})\s*€\s*par\s*(?:dose|lavage|cap(?:s)?)"]:
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
    for m in re.finditer(r"(\d{1,3}(?:[.,]\d{2}))\s*€", txt2):
        end = m.end(); tail = (txt2[end:end+12] or '').lower()
        if '/l' in tail or 'par l' in tail:
            continue
        v = norm_price(m.group(1))
        if v and 0.2 <= v <= 200:
            return v
    return None

# ----------------- orchestrateur -----------------
def extract_from_html_common(html: str, title_hint: str, host: str):
    title, price = price_from_jsonld(html)
    if price is None:
        title, price = price_from_scripts(html)
    if price is None:
        title, price = price_from_html(html)

    # €/L → total
    unit_pl = extract_unit_price_per_liter(html)
    if unit_pl is not None:
        lit = parse_liters_from_text(title_hint or title or "")
        if lit is None:
            lit = parse_liters_from_text(html_to_text(html)[:6000])
        if lit and lit > 0:
            computed = round(unit_pl * lit, 2)
            if price is None or abs(price - unit_pl) < 0.06 or price < unit_pl:
                price = computed

    # €/kg → total
    unit_kg = extract_unit_price_per_kg(html)
    if unit_kg is not None:
        kg = parse_weight_kg_from_text(title_hint or title or "")
        if kg is None:
            kg = parse_weight_kg_from_text(html_to_text(html)[:6000])
        if kg and kg > 0:
            computed = round(unit_kg * kg, 2)
            if price is None or abs(price - unit_kg) < 0.1 or price < unit_kg:
                price = computed

    # €/dose → total
    unit_dose = extract_unit_price_per_dose(html)
    if unit_dose is not None:
        n = parse_count_from_text(title_hint or title or "")
        if n is None:
            n = parse_count_from_text(html_to_text(html)[:6000])
        if n and n > 0:
            computed = round(unit_dose * n, 2)
            if price is None or price < unit_dose or abs(price - unit_dose) < 0.1:
                price = computed

    # Intermarché: éviter les prix de carrousel
    if 'intermarche.com' in host:
        p_first = first_price_before_marker(html)
        if p_first and price and price > p_first * 1.5:
            price = p_first

    return title, price

# ----------------- Playwright CDP -----------------
def engine_playwright(url: str, store_root: str):
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        ctx = browser.contexts[0] if browser.contexts else browser.new_context(locale="fr-FR")
        page = ctx.new_page()
        page.set_default_timeout(15000)
        # pré-chauffe referer
        page.goto(store_root, wait_until="domcontentloaded")
        page.goto(url, referer=store_root, wait_until="domcontentloaded")
        for _ in range(5):
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            page.wait_for_timeout(600)
        html = page.content()
        maybe_dump(html, url, 'cdp')
        host = (urlparse(url).hostname or '').lower()
        title, price = extract_from_html_common(html, page.title(), host)
        if price is None:
            page.wait_for_timeout(800)
            html = page.content()
            maybe_dump(html, url, 'cdp2')
            title, price = extract_from_html_common(html, page.title(), host)
        return title, price

# ----------------- main -----------------
def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "missing url"}))
        return
    url = sys.argv[1].strip()
    host = (urlparse(url).hostname or '').lower()
    # store root pour le referer (Leclerc Drive, etc.)
    store_root = re.sub(r"^(https?://[^/]+/magasin-[^/]+/).*", r"\1", url) if "/magasin-" in url else re.sub(r"^(https?://[^/]+/).*", r"\1", url)
    if not store_root.endswith("/"): store_root += "/"

    try:
        title, price = engine_playwright(url, store_root)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return

    if price is None:
        print(json.dumps({"ok": False, "error": "price not found"}))
        return

    print(json.dumps({"ok": True, "url": url, "title": title or "", "price": price, "currency": "EUR"}, ensure_ascii=False))

if __name__ == '__main__':
    main()