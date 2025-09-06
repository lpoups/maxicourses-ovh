#!/usr/bin/env python3
# Maxicourses — Scraper multi-enseignes (serveur + local)
# Serveur OVH: HTTP direct (urllib), aucune dépendance obligatoire.
# Local: Playwright CDP (--attach ou MAXI_CDP=1) et/ou Selenium undetected si dispo.
# Extraction: JSON-LD, scripts, HTML visible + conversions €/L, €/kg, €/dose.
# Debug: si le prix est introuvable, on sauvegarde automatiquement l'HTML dans /api/debug.
#        si MAXI_DUMP=1 est défini, on sauvegarde aussi quand un prix est trouvé.

import sys, json, re, time, os, html as htmllib, gzip, io, subprocess
from urllib.parse import urlparse, parse_qs, urlsplit
from urllib.request import Request, build_opener, HTTPCookieProcessor
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

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
    txt = re.sub(r"(?is)<script[\s\S]*?</script>", " ", html or "")
    txt = re.sub(r"(?is)<style[\s\S]*?</style>", " ", txt)
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
            unit_candidates.append(v); continue
        if 0.2 <= v <= 200 and (best_total is None or v < best_total):
            best_total = v

    # Prix flottant "price": "9,09" — éviter unit/per dans la clé
    for m in re.finditer(r'(?i)"(?P<key>[^"\n]*price[^"\n]*)"\s*:\s*"?(?P<val>\d+(?:[.,]\d{1,2}))"?', html or ""):
        key = m.group('key').lower()
        v = norm_price(m.group('val'))
        if not v: continue
        if any(h in key for h in PRICE_UNIT_HINTS):
            unit_candidates.append(v); continue
        if 0.2 <= v <= 200 and (best_total is None or v < best_total):
            best_total = v

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
    for rgx in [r"(\d+[.,]\d{1,2})\s*€\s*\/\s*kg", r"(\d+[.,]\d{1,2})\s*€\/kg", r"(\d+[.,]\d{1,2})\s*€\s*par\s*kg"]:
        m = re.search(rgx, txt or "", re.I)
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

# Helper: Carrefour autoclick from search results
def _carrefour_autoclick_product(page, url: str) -> bool:
    try:
        # Parse query to extract numbers/tokens for scoring
        u = urlsplit(url)
        q = (parse_qs(u.query).get("q") or [""])[0].lower()
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

        # Wait for product anchors then score by the surrounding article text
        page.wait_for_selector('a[href^="/p/"]', timeout=15000)
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

def extract_from_html_common(html: str, title_hint: str, host: str):
    title, price = price_from_jsonld(html)
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
    if unit_kg is not None:
        kg_vals = parse_weights_kg_all(title_hint or title or "")
        if not kg_vals:
            kg_vals = parse_weights_kg_all(html_to_text(html)[:6000])
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

    # Heuristique: si on a un prix unitaire €/kg ou €/L, choisir comme prix total le plus grand montant < à ce unitaire
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

    # Choix final du prix: privilégier les totaux calculés cohérents
    totals = []
    if price is not None:
        totals.append(price)
    for v in (computed_from_liters, computed_from_kg, computed_from_dose):
        if v is not None:
            totals.append(v)
    totals = [v for v in totals if 0.2 <= v <= 200]
    if totals:
        price = max(totals)

    return title, price, unit_hint

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

# Helper: fetch a page and return (code, final_url, html)
def fetch_raw_with_meta(url: str, referer: str):
    """Fetch a page with browser-like headers and return (code, final_url, html)."""
    cj = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cj))
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate',
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

def fetch_playwright_html(url: str, referer: str = None, wait_puzzle: bool = True, autoclick: bool = True) -> dict:
    # --- Playwright HTML fetcher for /fetch attach=1 ---
    if not PW_OK:
        return {"ok": False, "code": None, "final_url": None, "html": "", "bot_protection": False}

    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
    base = referer or re.sub(r"^(https?://[^/]+/).*", r"\1", url)

    with sync_playwright() as p:
        browser = None
        own_browser = False
        # 1) Try to attach to an already running Chrome over CDP
        try:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        except Exception:
            browser = None
        # 2) Fallback: launch a new (headed) Chromium if attach failed
        if browser is None:
            try:
                own_browser = True
                browser = p.chromium.launch(headless=False, args=[
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

        # Optionally wait for human to solve a puzzle/wall if present
        if wait_puzzle:
            try:
                _wait_if_bot_puzzle(page, timeout_ms=180000)
            except Exception:
                pass

        # Try auto-click again once page is stable
        try:
            cur_url = page.url or url
        except Exception:
            cur_url = url
        if autoclick and isinstance(cur_url, str) and ("carrefour.fr" in cur_url) and ("/s?" in cur_url or cur_url.endswith("/s")):
            try:
                _carrefour_autoclick_product(page, cur_url)
            except Exception:
                pass

        # Let dynamic prices render
        for _ in range(6):
            try:
                page.mouse.wheel(0, 1000)
            except Exception:
                pass
            page.wait_for_timeout(400)

        html = ""
        try:
            html = page.content()
        except Exception:
            html = ""

        result = {
            "ok": True if html else False,
            "code": 200 if html else None,
            "final_url": None,
            "html": html or "",
            "bot_protection": is_bot_protection(html) if isinstance(html, str) else False,
        }
        try:
            result["final_url"] = page.url
        except Exception:
            result["final_url"] = url

        # Close only if we launched the browser ourselves
        if own_browser:
            try:
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
            browser = p.chromium.launch(headless=False, args=[
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
        # Si une barrière anti-bot est présente, attendre une résolution humaine (jusqu'à 4 min)
        try:
            _wait_if_bot_puzzle(page, timeout_ms=240000)
        except Exception:
            pass

        # Scrolls + idle pour laisser charger les prix dynamiques
        for _ in range(6):
            try:
                page.mouse.wheel(0, 1200)
            except Exception:
                pass
            page.wait_for_timeout(600)
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
                t, pz, uh = extract_from_html_common(html, page.title(), host)
                if pz is not None:
                    title, price = t, pz
                    unit_hint = uh
                    break
            except Exception:
                pass
            page.wait_for_timeout(800)

        # Fermer si on a lancé nous-mêmes le navigateur
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
                t, pz, uh = extract_from_html_common(html, driver.title, host)
                if pz is not None:
                    title = t; price = pz; unit_hint = uh; break
        return title, price, unit_hint
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
            title, price, uhint = extract_from_html_common(html, "", host)
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
            tpu = engine_playwright(url, store_root)
            if isinstance(tpu, tuple) and len(tpu) == 3:
                title, price, uhint_pw = tpu
            else:
                title, price = tpu
                uhint_pw = {}
        except Exception:
            title, price, uhint_pw = (None, None, {})

    # 3) Local: Selenium si demandé (MAXI_SELENIUM=1)
    uhint_se = {}
    if price is None and SEL_OK and os.environ.get('MAXI_SELENIUM') == '1':
        try:
            tpu = engine_selenium(url, store_root)
            if isinstance(tpu, tuple) and len(tpu) == 3:
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
        # Merge unit hints from extractor (direct/PW/SE) avec garde sur la quantité
        for src in (locals().get('uhint', {}), locals().get('uhint_pw', {}), locals().get('uhint_se', {})):
            if not isinstance(src, dict):
                continue
            for k, v in src.items():
                if v is None or unit.get(k) not in (None, 0):
                    continue
                if k == 'per_liter' and not unit.get('liters'):
                    continue
                if k == 'per_kg' and not unit.get('kg'):
                    continue
                if k == 'per_dose' and not unit.get('doses'):
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
        print(json.dumps(out))
        return

    out = {"ok": True, "url": url, "title": title or "", "price": price, "currency": "EUR", "unit": unit}
    if 'debug_path' in locals() and debug_path:
        out["debug_dump"] = debug_path
    print(json.dumps(out, ensure_ascii=False))

# ---------- Lightweight HTTP worker ----------

def _run_self(url: str) -> dict:
    """Invoke this script as a subprocess to reuse main() logic and capture JSON."""
    try:
        cmd = [sys.executable, os.path.abspath(__file__), url, '--attach']
        env = os.environ.copy()
        # Favoriser l'attache CDP si dispo
        env.setdefault('MAXI_CDP', '1')
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=90)
        out = p.stdout.strip()
        return json.loads(out) if out else {"ok": False, "error": "empty_output", "stderr": p.stderr}
    except Exception as e:
        return {"ok": False, "error": f"subprocess_error: {e}"}

class _Handler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, payload: dict):
        data = json.dumps(payload).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)

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
                if not url:
                    return self._send_json(400, {"ok": False, "error": "missing url"})
                res = _run_self(url)
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
                if not url:
                    return self._send_json(400, {"ok": False, "error": "missing url"})
                res = _run_self(url)
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

            return self._send_json(404, {"ok": False, "error": "not found"})
        except Exception as e:
            return self._send_json(500, {"ok": False, "error": str(e)})

if __name__ == '__main__':
    # Server mode: python3 scraper.py --serve 0.0.0.0:5001
    if '--serve' in sys.argv:
        try:
            i = sys.argv.index('--serve')
            bind = sys.argv[i+1] if i+1 < len(sys.argv) else '127.0.0.1:5001'
        except Exception:
            bind = '127.0.0.1:5001'
        host, port = (bind.split(':', 1) + ['5001'])[:2]
        httpd = ThreadingHTTPServer((host, int(port)), _Handler)
        print(f"[scraper] serving on http://{host}:{port}")
        httpd.serve_forever()
    else:
        main()