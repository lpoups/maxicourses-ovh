# finder.py
# Étape 1/3 — Scaffold solide et extensible, 100% code “dans le dur”.
from __future__ import annotations
import argparse
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from typing import Any, List, Dict, Iterable, Optional, Tuple, Protocol, Callable
import re
import os
import atexit
import json
import sys
from pathlib import Path
try:
    from ai_helpers import USE_AI_ASSIST, suggest_search_queries  # type: ignore
except Exception:  # pragma: no cover - AI optional
    USE_AI_ASSIST = False  # type: ignore
    suggest_search_queries = None  # type: ignore
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except Exception:  # pragma: no cover - Playwright optional
    sync_playwright = None
    PlaywrightTimeoutError = Exception  # type: ignore
from .text_utils import is_pack_or_bundle
from descriptor_store import get_descriptor
HtmlProvider = Callable[[str], Optional[str]]
ImageCompareProvider = Callable[[Optional[str], Optional[str]], bool]
PLAYWRIGHT_SINGLETON: Dict[str, Optional[object]] = {
    "playwright": None,
    "browser": None,
    "context": None,
}
LECLERC_LISTING_IMAGES: Dict[str, str] = {}


def _normalize_leclerc_url_key(url: str) -> str:
    return url.split("#", 1)[0].strip()


def _store_leclerc_listing_image(url: Optional[str], image_url: Optional[str]) -> None:
    if not url or not image_url:
        return
    key = _normalize_leclerc_url_key(url)
    value = image_url.strip()
    if not key or not value:
        return
    LECLERC_LISTING_IMAGES[key] = value
    if len(LECLERC_LISTING_IMAGES) > 128:
        try:
            LECLERC_LISTING_IMAGES.pop(next(iter(LECLERC_LISTING_IMAGES)))
        except StopIteration:
            pass


def _lookup_leclerc_listing_image(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    return LECLERC_LISTING_IMAGES.get(_normalize_leclerc_url_key(url))


def _close_playwright() -> None:
    pw = PLAYWRIGHT_SINGLETON.get("playwright")
    browser = PLAYWRIGHT_SINGLETON.get("browser")
    context = PLAYWRIGHT_SINGLETON.get("context")
    try:
        if context is not None:
            context.close()
    except Exception:
        pass
    try:
        if browser is not None:
            browser.close()
    except Exception:
        pass
    try:
        if pw is not None:
            pw.stop()
    except Exception:
        pass
    PLAYWRIGHT_SINGLETON.update({"playwright": None, "browser": None, "context": None})
def _ensure_sync_playwright_context():
    if sync_playwright is None:
        return None
    if PLAYWRIGHT_SINGLETON["context"] is not None:
        return PLAYWRIGHT_SINGLETON["context"]
    try:
        pw = sync_playwright().start()
    except Exception:
        return None
    browser = None
    context = None
    try:
        cdp_url = os.environ.get("CDP_URL")
        if cdp_url:
            browser = pw.chromium.connect_over_cdp(cdp_url)
            existing = browser.contexts
            context = existing[0] if existing else browser.new_context()
        else:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context()
    except Exception:
        try:
            pw.stop()
        except Exception:
            pass
        return None
    PLAYWRIGHT_SINGLETON.update({"playwright": pw, "browser": browser, "context": context})
    atexit.register(_close_playwright)
    return context
def _make_monoprix_image_provider() -> Optional[ImageCompareProvider]:
    try:
        from .image_matching import _hash_variants, _hash_distance
        from PIL import Image
        import io
        import base64
    except ImportError:
        return None

    if sync_playwright is None:
        return None
    context = _ensure_sync_playwright_context()
    if context is None:
        print("[DEBUG] Finder: No sync context available", file=sys.stderr)
        return None

    def _fetch_image_sync(url: str) -> Optional[bytes]:
        page = None
        try:
            page = context.new_page()
            # Navigate to origin to ensure cookies/fetch works
            try:
                page.goto("https://courses.monoprix.fr/robots.txt", timeout=10000, wait_until="commit")
            except Exception:
                pass # Try anyway if load fails (might be net split but context exists)
            
            # Generic fetch wrapper
            b64 = page.evaluate(
                """async (url) => {
                    const resp = await fetch(url);
                    if (!resp.ok) {
                        return "ERROR:" + resp.status;
                    }
                    const blob = await resp.blob();
                    return new Promise((resolve, reject) => {
                        const reader = new FileReader();
                        reader.onloadend = () => resolve(reader.result);
                        reader.onerror = reject;
                        reader.readAsDataURL(blob);
                    });
                }""",
                url
            )
            # Handle error
            if isinstance(b64, str) and b64.startswith("ERROR:"):
                print(f"[DEBUG] Finder fetch HTTP Error: {b64} for {url}", file=sys.stderr)
                return None

            # data:image/jpeg;base64,.....
            if isinstance(b64, str) and "," in b64:
                return base64.b64decode(b64.split(",", 1)[1])
            return None
        except Exception as e:
            print(f"[DEBUG] Finder fetch failed for {url}: {e}", file=sys.stderr)
            return None
        finally:
            if page: 
                try: 
                    page.close() 
                except: 
                    pass

    def _provider(_self, seed_url: Optional[str], cand_url: Optional[str]) -> bool:
        if not seed_url or not cand_url:
            return False
        
        # 1. Download images via Browser (bypass 403)
        print(f"[DEBUG] Finder: Fetching images via sync browser...", file=sys.stderr)
        seed_bytes = _fetch_image_sync(seed_url)
        cand_bytes = _fetch_image_sync(cand_url)

        if not seed_bytes or not cand_bytes:
            print("[DEBUG] Finder: Failed to fetch image bytes", file=sys.stderr)
            return False

        # 2. Compute Hashes
        try:
            seed_img = Image.open(io.BytesIO(seed_bytes))
            cand_img = Image.open(io.BytesIO(cand_bytes))
            
            h1_list = _hash_variants(seed_img)
            h2_list = _hash_variants(cand_img)
            
            min_dist = 64
            for h1 in h1_list:
                for h2 in h2_list:
                    d = _hash_distance(h1, h2)
                    if d < min_dist:
                        min_dist = d
            
            print(f"[DEBUG] Finder Hash Distance: {min_dist}", file=sys.stderr)
            if min_dist <= 16:  # Standard threshold
                return True
            
            # 3. AI Fallback (if enabled and hash failed)
            print("[DEBUG] Finder: Trying AI Vision Fallback...", file=sys.stderr)
            from ai_helpers import compute_vision_similarity
            if compute_vision_similarity:
                # Re-encode to base64 for API
                b64_s = base64.b64encode(seed_bytes).decode('ascii')
                b64_c = base64.b64encode(cand_bytes).decode('ascii')
                print("[DEBUG] Finder: Calling compute_vision_similarity...", file=sys.stderr)
                resp = compute_vision_similarity(b64_s, b64_c)
                print(f"[DEBUG] Finder: AI Response: {resp.status} - {resp.data}", file=sys.stderr)
                if resp.status == "ok" and resp.data.get("match") is True:
                     # Log could be added here if we had access to audit
                     return True

        except Exception as e:
            print(f"[DEBUG] Finder Provider Error: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()

        return False

    return _provider
def _make_leclerc_html_provider() -> Optional[HtmlProvider]:
    if sync_playwright is None:
        return None
    context = _ensure_sync_playwright_context()
    if context is None:
        return None
    @lru_cache(maxsize=64)
    def _fetch(url: str) -> Optional[str]:
        if not url:
            return None
        page = None
        try:
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            try:
                page.wait_for_selector("h1", timeout=12000)
            except Exception:
                pass
            page.wait_for_timeout(600)
            html = page.content()
            if html and "datadome" in html.lower():
                page.wait_for_timeout(1200)
                html = page.content()
            return html
        except Exception:
            return None
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass
    return _fetch
def _clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return " ".join(str(value).split())
def _compose_keyword_query(keywords: List[str], max_length: int = 40) -> str:
    tokens = [t.strip() for t in keywords if isinstance(t, str) and t.strip()]
    query = " ".join(tokens)
    if len(query) <= max_length:
        return query
    trimmed: List[str] = []
    for token in tokens:
        trial = " ".join(trimmed + [token]) if trimmed else token
        if len(trial) <= max_length or not trimmed:
            trimmed.append(token)
        else:
            break
    return " ".join(trimmed)[:max_length].rstrip()
def _make_leclerc_listing_provider() -> Optional[Callable[[List[str]], List[Tuple[str, str, str]]]]:
    if sync_playwright is None:
        return None
    context = _ensure_sync_playwright_context()
    if context is None:
        return None
    store_url = os.environ.get(
        "LECLERC_FINDER_STORE_URL",
        "https://fd12-courses.leclercdrive.fr/magasin-173301-173301-bruges.aspx",
    )
    @lru_cache(maxsize=128)
    def _search_cached(query: str) -> List[Tuple[str, str, str]]:
        if not query:
            return []
        page = None
        from urllib.parse import urljoin
        results: List[Tuple[str, str, str]] = []
        try:
            page = context.new_page()
            page.goto(store_url, wait_until="domcontentloaded", timeout=15000)
            try:
                consent = page.query_selector("#onetrust-accept-btn-handler")
                if consent:
                    consent.click()
                    page.wait_for_timeout(600)
            except Exception:
                pass
            search_box = page.query_selector("input[id*='rechercheTexte']")
            if not search_box:
                return []
            
            # Robust Search Interaction
            try:
                search_box.click(force=True, timeout=2000)
                page.evaluate("el => el.value = ''", search_box)
                page.wait_for_timeout(100)
                search_box.type(query, delay=20)
                page.wait_for_timeout(200)
                page.keyboard.press("Enter")
            except Exception:
                # Retry once if interaction failed
                try: 
                     page.evaluate(f"document.querySelector('input[id*=\"rechercheTexte\"]').value = '{query}'")
                     page.keyboard.press("Enter")
                except Exception:
                     return []

            try:
                page.wait_for_selector("li.liWCRS310_Product", timeout=8000)
            except PlaywrightTimeoutError:
                return []
            
            page.wait_for_timeout(500)
            cards = page.query_selector_all("li.liWCRS310_Product")
            for card in cards:
                try:
                    link = card.query_selector("a.aWCRS310_Product")
                    if not link:
                        continue
                    href = link.get_attribute("href") or ""
                    if not href:
                        continue
                    title = _clean_text(link.inner_text())
                    snippet_node = card.query_selector(".divWCRS310_Description") or card
                    snippet = _clean_text(snippet_node.inner_text() if snippet_node else "")
                    abs_url = urljoin(page.url, href)
                    # Helper for thumb extraction would go here, simplified for brevity as text matching is primary
                    results.append((abs_url, title, snippet))
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            if page:
                try: page.close()
                except Exception: pass
        return results

    def _provider(keywords: List[str]) -> List[Tuple[str, str, str]]:
        # Agentic Loop
        try:
            from .repository import ProductRepository
            repo = ProductRepository()
        except ImportError:
            repo = None
            
        seen_queries = set()
        candidates = []
        for k in keywords:
            if not isinstance(k, str): continue
            clean_k = " ".join(k.split())
            if not clean_k or clean_k in seen_queries: continue
            seen_queries.add(clean_k)
            candidates.append(clean_k)
            
        for i, query in enumerate(candidates):
            if len(query) > 50: query = query[:50].rstrip()

            # Check Blacklist
            if repo and repo.is_query_blacklisted("leclerc", query):
                continue
            
            res = _search_cached(query)
            if res:
                return res
            else:
                 # Record Failure
                 if repo:
                     repo.record_failure("leclerc", query)
        return []
    return _provider

def _make_monoprix_listing_provider() -> Optional[Callable[[List[str]], List[Tuple[str, str, str]]]]:
    if sync_playwright is None:
        return None
    context = _ensure_sync_playwright_context()
    if context is None:
        return None

    @lru_cache(maxsize=128)
    def _provider_cached(query: str) -> List[Tuple[str, str, str]]:
        page = None
        results = []
        try:
            page = context.new_page()
            # Monoprix Search
            page.goto("https://www.monoprix.fr", wait_until="domcontentloaded", timeout=15000)
            try:
                consent = page.query_selector("#onetrust-accept-btn-handler")
                if consent:
                    consent.click()
                    page.wait_for_timeout(600)
            except Exception:
                pass
            search_box = page.query_selector("input[id*='rechercheTexte']")
            if not search_box:
                return []
            
            # Robust Search Interaction
            try:
                search_box.click(force=True, timeout=2000)
                page.evaluate("el => el.value = ''", search_box)
                page.wait_for_timeout(100)
                search_box.type(query, delay=20)
                page.wait_for_timeout(200)
                page.keyboard.press("Enter")
            except Exception:
                # Retry once if interaction failed
                try: 
                     page.evaluate(f"document.querySelector('input[id*=\"rechercheTexte\"]').value = '{query}'")
                     page.keyboard.press("Enter")
                except Exception:
                     return []

            try:
                page.wait_for_selector("li.liWCRS310_Product", timeout=8000)
            except PlaywrightTimeoutError:
                return []
            
            page.wait_for_timeout(500)
            cards = page.query_selector_all("li.liWCRS310_Product")
            for card in cards:
                try:
                    link = card.query_selector("a.aWCRS310_Product")
                    if not link:
                        continue
                    href = link.get_attribute("href") or ""
                    if not href:
                        continue
                    title = _clean_text(link.inner_text())
                    snippet_node = card.query_selector(".divWCRS310_Description") or card
                    snippet = _clean_text(snippet_node.inner_text() if snippet_node else "")
                    abs_url = urljoin(page.url, href)
                    results.append((abs_url, title, snippet))
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            if page:
                try: page.close()
                except Exception: pass
        return results

    def _provider(keywords: List[str]) -> List[Tuple[str, str, str]]:
        seen_queries = set()
        all_results = []
        for k in keywords:
            if not isinstance(k, str): continue
            clean_k = " ".join(k.split())
            if not clean_k or clean_k in seen_queries: continue
            seen_queries.add(clean_k)
            all_results.extend(_provider_cached(clean_k))
        return all_results
    return _provider

def _make_auchan_listing_provider() -> Optional[Callable[[List[str]], List[Tuple[str, str, str]]]]:
    if sync_playwright is None:
        return None
    context = _ensure_sync_playwright_context()
    if context is None:
        return None

    @lru_cache(maxsize=128)
    def _provider_cached(query: str) -> List[Tuple[str, str, str]]:
        page = None
        results = []
        try:
            page = context.new_page()
            page.goto("https://www.auchan.fr", wait_until="domcontentloaded", timeout=15000)
            try:
                consent = page.query_selector("#onetrust-accept-btn-handler")
                if consent:
                    consent.click()
                    page.wait_for_timeout(600)
            except Exception:
                pass
            
            search_box = page.query_selector("input[placeholder*='Rechercher']") or page.query_selector("input[data-testid='search-input']")
            if not search_box:
                return []
            
            try:
                search_box.fill("")
                search_box.type(query, delay=20)
                page.keyboard.press("Enter")
            except Exception:
                return []
                
            try:
                page.wait_for_selector("article.product-thumbnail, a[href*='/produit/']", timeout=8000)
            except PlaywrightTimeoutError:
                return []
                
            page.wait_for_timeout(500)
            cards = page.query_selector_all("article.product-thumbnail")
            if not cards:
                cards = page.query_selector_all("a[href*='/produit/']")
                
            for card in cards:
                try:
                    if card.evaluate("el => el.tagName") == "A":
                        link = card
                        snippet_node = card
                    else:
                        link = card.query_selector("a[href*='/produit/']") or card.query_selector("a")
                        snippet_node = card
                    
                    if not link: continue
                    href = link.get_attribute("href") or ""
                    title = _clean_text(link.inner_text())  # Often title is in the link text or nested
                    if not title and snippet_node:
                         # Try to find specific title class
                         t_node = snippet_node.query_selector(".product-thumbnail__title, [class*='title']")
                         if t_node: title = _clean_text(t_node.inner_text())

                    snippet = _clean_text(snippet_node.inner_text())
                    abs_url = urljoin(page.url, href)
                    results.append((abs_url, title, snippet))
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            if page:
                try: page.close()
                except Exception: pass
        return results

    def _provider(keywords: List[str]) -> List[Tuple[str, str, str]]:
        seen_queries = set()
        all_results = []
        for k in keywords:
            if not isinstance(k, str): continue
            clean_k = " ".join(k.split())
            if not clean_k or clean_k in seen_queries: continue
            seen_queries.add(clean_k)
            all_results.extend(_provider_cached(clean_k))
        return all_results
    return _provider

def _make_intermarche_listing_provider() -> Optional[Callable[[List[str]], List[Tuple[str, str, str]]]]:
    if sync_playwright is None:
        return None
    context = _ensure_sync_playwright_context()
    if context is None:
        return None

    @lru_cache(maxsize=128)
    def _provider_cached(query: str) -> List[Tuple[str, str, str]]:
        page = None
        results = []
        try:
            page = context.new_page()
            # Direct search URL for Intermarche
            encoded = quote(query, safe="")
            page.goto(f"https://www.intermarche.com/recherche/{encoded}", wait_until="domcontentloaded", timeout=15000)
            
            # Simple cookie handling
            try:
                page.click("button:has-text('Tout accepter')", timeout=1000)
            except Exception:
                pass
            try:
                page.click("#onetrust-accept-btn-handler", timeout=500)
            except Exception:
                pass

            try:
                page.wait_for_selector("a[href*='/produit/']", timeout=10000)
            except PlaywrightTimeoutError:
                return []
                
            page.wait_for_timeout(500)
            cards = page.query_selector_all("a[href*='/produit/']")
            for card in cards:
                try:
                    href = card.get_attribute("href") or ""
                    if not href: continue
                    title = _clean_text(card.inner_text())
                    # Snippet extraction if possible (parent usually has more info)
                    snippet = title
                    parent = card.xpath("..")
                    if parent:
                         snippet = _clean_text(parent[0].inner_text())
                    
                    abs_url = urljoin(page.url, href)
                    results.append((abs_url, title, snippet))
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            if page:
                try: page.close()
                except Exception: pass
        return results

    def _provider(keywords: List[str]) -> List[Tuple[str, str, str]]:
        seen_queries = set()
        all_results = []
        for k in keywords:
            if not isinstance(k, str): continue
            clean_k = " ".join(k.split())
            if not clean_k or clean_k in seen_queries: continue
            seen_queries.add(clean_k)
            all_results.extend(_provider_cached(clean_k))
        return all_results
    return _provider

def _make_courseu_listing_provider() -> Optional[Callable[[List[str]], List[Tuple[str, str, str]]]]:
    if sync_playwright is None:
        return None
    context = _ensure_sync_playwright_context()
    if context is None:
        return None

    @lru_cache(maxsize=128)
    def _provider_cached(query: str) -> List[Tuple[str, str, str]]:
        page = None
        results = []
        try:
            page = context.new_page()
            # Direct search URL for Courses U
            encoded = quote(query)
            page.goto(f"https://www.coursesu.com/recherche?q={encoded}", wait_until="domcontentloaded", timeout=15000)

            try:
                page.click("#onetrust-accept-btn-handler", timeout=1000)
            except Exception:
                pass
                
            try:
                page.wait_for_selector("a[href*='/p/']", timeout=10000)
            except PlaywrightTimeoutError:
                return []
            
            page.wait_for_timeout(500)
            cards = page.query_selector_all("a[href*='/p/']")
            for card in cards:
                try:
                    href = card.get_attribute("href") or ""
                    if not href: continue
                    title = _clean_text(card.inner_text())
                    snippet = title
                    abs_url = urljoin(page.url, href)
                    results.append((abs_url, title, snippet))
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            if page:
                try: page.close()
                except Exception: pass
        return results

    def _provider(keywords: List[str]) -> List[Tuple[str, str, str]]:
        seen_queries = set()
        all_results = []
        for k in keywords:
            if not isinstance(k, str): continue
            clean_k = " ".join(k.split())
            if not clean_k or clean_k in seen_queries: continue
            seen_queries.add(clean_k)
            all_results.extend(_provider_cached(clean_k))
        return all_results
    return _provider

def _make_casino_listing_provider() -> Optional[Callable[[List[str]], List[Tuple[str, str, str]]]]:
    if sync_playwright is None:
        return None
    context = _ensure_sync_playwright_context()
    if context is None:
        return None

    @lru_cache(maxsize=128)
    def _provider_cached(query: str) -> List[Tuple[str, str, str]]:
        page = None
        results = []
        try:
            page = context.new_page()
            # Casino Shop search (Store TZ193 default)
            encoded = quote(query)
            page.goto(f"https://www.mescoursesdeproximite.com/recherche/TZ193?produit_recherche={encoded}", wait_until="domcontentloaded", timeout=15000)

            try:
                page.wait_for_selector("div.card-produit-vignette", timeout=8000)
            except PlaywrightTimeoutError:
                return []
            
            page.wait_for_timeout(500)
            cards = page.query_selector_all("div.card-produit-vignette")
            for card in cards:
                try:
                    link = card.query_selector(".produit-desc a[href]")
                    if not link: continue
                    href = link.get_attribute("href") or ""
                    
                    title_node = card.query_selector(".produit-desc h3")
                    if title_node:
                        title = _clean_text(title_node.inner_text())
                    else:
                        title = _clean_text(link.inner_text())
                    
                    snippet = title
                    abs_url = urljoin(page.url, href)
                    results.append((abs_url, title, snippet))
                except Exception:
                    continue
        except Exception:
            pass
        finally:
            if page:
                try: page.close()
                except Exception: pass
        return results

    def _provider(keywords: List[str]) -> List[Tuple[str, str, str]]:
        seen_queries = set()
        all_results = []
        for k in keywords:
            if not isinstance(k, str): continue
            clean_k = " ".join(k.split())
            if not clean_k or clean_k in seen_queries: continue
            seen_queries.add(clean_k)
            all_results.extend(_provider_cached(clean_k))
        return all_results
    return _provider

def _make_subprocess_listing_provider(script_name: str, adapter_name: str, specific_env: dict = None) -> Optional[Callable[[List[str]], List[Tuple[str, str, str]]]]:
    # Generic provider that calls the corresponding fetch_*.py script via subprocess
    import subprocess
    import sys
    import json
    import os
    
    script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), script_name)
    
    if not os.path.exists(script_path):
        return None

    @lru_cache(maxsize=128)
    def _provider_cached(query: str) -> List[Tuple[str, str, str]]:
        env = os.environ.copy()
        env["EAN"] = query
        env["HEADLESS"] = "1"
        if specific_env:
            env.update(specific_env)
        
        results = []
        try:
            # Run with timeout (60s for slow sites like Auchan)
            res = subprocess.run(
                [sys.executable, script_path],
                env=env,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if res.stdout:
                lines = res.stdout.strip().splitlines()
                data = None
                # Try strict JSON first, then line by line
                try:
                    data = json.loads(res.stdout, strict=False)
                except:
                     pass

                if not data:
                    # Robust search for JSON object using regex
                    # Because logs might be mixed with JSON or JSON might be formatted
                    import re
                    # Look for { "status": "OK" ... } or just { ... } that parses
                    try:
                        clean_stdout = res.stdout.strip()
                        start = clean_stdout.find("{")
                        end = clean_stdout.rfind("}")
                        if start != -1 and end != -1:
                             candidate_str = clean_stdout[start:end+1]
                             try:
                                 data = json.loads(candidate_str, strict=False)
                             except:
                                 pass
                    except:
                        pass
                
                if data:
                    title = data.get("title")
                    # Construct valid snippet for AI
                    raw_text = f"{title} {data.get('quantity') or ''} {data.get('unit_price') or ''} {data.get('price') or ''}"
                    url = data.get("url") or f"https://mock-{adapter_name}/{query}"
                    results.append((url, title, raw_text))

        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass
        return results

    def _provider(keywords: List[str]) -> List[Tuple[str, str, str]]:
        # This provider usually takes EAN as input list
        seen = set()
        res = []
        for k in keywords:
            if k not in seen:
                seen.add(k)
                res.extend(_provider_cached(k))
        return res
    return _provider
# ---------- Modèle ----------
@dataclass
class ProductDescriptor:
    title: str = ""
    brand: str = ""
    kind: str = ""            # ex: "miel de fleurs"
    qty: str = ""             # ex: "500 g" ou "1,75 L"
    price: Optional[float] = None # Price found
    quantity: Optional[str] = None # Normalized quantity
    qualifiers: List[str] = field(default_factory=list)  # ex: ["bio", "sans sucre"]
    ean: Optional[str] = None
    image_url: Optional[str] = None
    source: str = ""          # nom d’enseigne adapter
    raw_text: str = ""        # descriptif long brut pour matching
    seed_query: str = ""      # requete seed (titre riche)
    leclerc_queries: List[str] = field(default_factory=list) # requetes specifiques leclerc
    def tokens(self) -> List[str]:
        txt = " ".join([self.title, self.brand, self.kind, self.qty, " ".join(self.qualifiers), self.raw_text])
        txt = re.sub(r"[^a-z0-9àâçéèêëîïôûùüÿœ\s\-\.]", " ", txt.lower())
        return [t for t in re.split(r"\s+", txt) if t]


def _descriptor_to_product(payload: Optional[Dict[str, Any]], *, source: str) -> Optional[ProductDescriptor]:
    if not isinstance(payload, dict):
        return None
    canonical = payload.get("canonical") if isinstance(payload.get("canonical"), dict) else {}
    title = payload.get("name") or payload.get("seed_primary_name") or canonical.get("name_core") or ""
    brand = payload.get("brand") or canonical.get("brand") or ""
    qty = payload.get("quantity") or payload.get("seed_primary_quantity") or ""
    qualifiers = []
    for key in ("secondary_keywords", "qualifiers"):
        values = payload.get(key)
        if isinstance(values, (list, tuple)):
            for item in values:
                if isinstance(item, str) and item not in qualifiers:
                    qualifiers.append(item)
    image_url = None
    images = payload.get("images") or canonical.get("images")
    if isinstance(images, (list, tuple)) and images:
        image_url = images[0]
    elif isinstance(payload.get("image"), str):
        image_url = payload.get("image")
    raw_parts = []
    for key in ("description", "seed_query", "note"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            raw_parts.append(value.strip())
    def infer_brand_from_title(raw_title: str, fallback: str) -> str:
        generic = {
            "boisson",
            "lait",
            "jus",
            "eau",
            "soda",
            "boite",
            "bouteille",
            "pack",
            "lot",
            "bio",
            "sans",
            "produit",
            "vegetal",
            "végétal",
            "amande",
            "grillee",
            "grillée",
            "vanille",
            "intense",
        }
        tokens = re.findall(r"[A-Za-zÀ-ÿ0-9']+", raw_title or "")
        for tok in tokens:
            norm = tok.lower()
            if norm in generic:
                continue
            if any(char.isalpha() for char in tok) and not any(char.isdigit() for char in tok):
                return tok.strip()
        # fallback: dernier token alpha non générique
        for tok in reversed(tokens):
            norm = tok.lower()
            if norm in generic:
                continue
            if any(char.isalpha() for char in tok) and not any(char.isdigit() for char in tok):
                return tok.strip()
        return fallback

    brand_clean = str(brand or "").strip()
    if not brand_clean or brand_clean.lower() in {"", "boisson", "produit", "marque"}:
        brand_clean = infer_brand_from_title(str(title or ""), brand_clean)

    return ProductDescriptor(
        title=str(title or ""),
        brand=brand_clean,
        kind="",
        qty=str(qty or ""),
        qualifiers=qualifiers,
        ean=str(payload.get("ean") or "") or None,
        image_url=image_url,
        source=source,
        raw_text=" \n".join(raw_parts),
        seed_query=payload.get("seed_query") or "",
        leclerc_queries=payload.get("leclerc_queries") or [],
    )
# ---------- Interfaces Adapters ----------
class EanSearch(Protocol):
    def search_by_ean(self, ean: str) -> Optional[ProductDescriptor]:
        ...
class KeywordSearch(Protocol):
    def search_by_keywords(self, keywords: List[str]) -> List[str]:
        """Retourne une liste d’URLs candidates (résultats de recherche)."""
        ...
    def parse_product_page(self, url: str) -> Optional[ProductDescriptor]:
        ...
class Adapter(Protocol):
    name: str
    supports_ean: bool
    supports_keywords: bool
    can_extract_ean_from_href: bool
    def hard_validate(self, src: "ProductDescriptor", url: str, pd: "ProductDescriptor") -> Optional[float]: ...
    def override_threshold(self) -> Optional[float]: ...
    def override_strict_qty(self) -> Optional[bool]: ...
    def html(self) -> HtmlProvider | None: ...
    def image_compare(self) -> Optional[ImageCompareProvider]: ...
# ---------- Moteur de consolidation ----------
class Consolidator:
    def __init__(self) -> None:
        self.sources: List[ProductDescriptor] = []
    def add(self, d: Optional[ProductDescriptor]) -> None:
        if d:
            self.sources.append(d)
    def merged(self) -> ProductDescriptor:
        # règle simple: privilégie champs les plus fréquents non vides parmi sources EAN-direct
        preferred_sources = {"seed", "canonical"}
        def pick(field: str, prefer_seed: bool = False) -> str:
            if prefer_seed:
                for src in self.sources:
                    source_label = (src.source or "").lower()
                    if source_label in preferred_sources:
                        value = getattr(src, field)
                        if value:
                            return value
            vals = [getattr(s, field) for s in self.sources if getattr(s, field)]
            if not vals:
                return ""
            # mode
            scores: Dict[str, int] = {}
            for v in vals:
                scores[v] = scores.get(v, 0) + 1
            return max(scores.items(), key=lambda kv: kv[1])[0]
        merged = ProductDescriptor(
            title=pick("title", prefer_seed=True),
            brand=pick("brand", prefer_seed=True),
            kind=pick("kind"),
            qty=pick("qty", prefer_seed=True),
            ean=next((s.ean for s in self.sources if s.ean), None),
            image_url=next((s.image_url for s in self.sources if s.image_url), None),
            source="consolidated",
            raw_text=" ".join({s.raw_text for s in self.sources if s.raw_text} | {s.title for s in self.sources if s.title}),
            seed_query=pick("seed_query", prefer_seed=True),
        )
        # leclerc_queries: union
        lq_all: List[str] = []
        for s in self.sources:
            for lq in s.leclerc_queries:
                if lq not in lq_all:
                    lq_all.append(lq)
        merged.leclerc_queries = lq_all
        # qualifiers: union pondérée
        q_all: Dict[str, int] = {}
        for s in self.sources:
            for q in s.qualifiers:
                q_all[q] = q_all.get(q, 0) + 1
        merged.qualifiers = [q for q, _n in sorted(q_all.items(), key=lambda kv: -kv[1])]
        return merged
# ---------- Générateur de mots-clés ----------
class KeywordGenerator:
    STOPWORDS = {
        "le",
        "la",
        "les",
        "de",
        "des",
        "du",
        "au",
        "aux",
        "d",
        "l",
        "et",
        "pour",
        "avec",
        "boire",
        "sans",
        "lot",
        "lots",
        "pack",
        "packs",
        "promo",
        "produit",
        "produits",
        "course",
        "courses",
        "drive",
        "magasin",
        "offre",
        "offres",
        "nouveau",
        "nouvelle",
        "format",
        "original",
        "grand",
        "grande",
        "qualite",
        "qualité",
        "marque",
        "supermarché",
        "supermarche",
    }

    GENERIC_TOKENS = {
        "cafe",
        "cafes",
        "café",
        "cafés",
        "boisson",
        "boissons",
        "produit",
        "produits",
        "arabica",
        "intensite",
        "intensité",
        "qualite",
        "qualité",
    }

    BOOST_SUBSTRINGS = (
        "capsul",
        "dosett",
        "pod",
        "supremo",
        "ristretto",
        "espresso",
        "nespresso",
    )

    def __init__(self, max_keywords: int = 4, max_length: int = 30) -> None:
        self.max_keywords = max_keywords
        self.max_length = max_length

    @staticmethod
    def _strip_accents(value: str) -> str:
        import unicodedata
        return "".join(ch for ch in unicodedata.normalize("NFD", value) if unicodedata.category(ch) != "Mn")

    def _normalize(self, value: Optional[str]) -> str:
        if not value:
            return ""
        value = self._strip_accents(value.lower())
        value = re.sub(r"[^a-z0-9]+", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    def _format_brand(self, value: Optional[str]) -> str:
        if not isinstance(value, str):
            return ""
        cleaned = re.sub(r"\s+", " ", value.strip())
        if not cleaned:
            return ""
        if cleaned.isupper():
            return cleaned.title()
        return cleaned

    def _format_quantity(self, value: Optional[str]) -> str:
        if not isinstance(value, str):
            return ""
        cleaned = value.strip()
        if not cleaned:
            return ""
        cleaned = cleaned.replace(",", ".")
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.upper()

    def _expand_quantity_variants(self, quantity: Optional[str]) -> List[str]:
        formatted = self._format_quantity(quantity)
        if not formatted:
            return []

        variants: List[str] = []
        seen: set[str] = set()

        def add_variant(text: str) -> None:
            candidate = text.strip()
            if not candidate:
                return
            key = candidate.upper()
            if key in seen:
                return
            seen.add(key)
            variants.append(candidate)

        add_variant(formatted)

        match = re.match(r"(?P<number>\d+(?:\.\d+)?)(?:\s*)?(?P<unit>ML|CL|L)\b", formatted)
        if match:
            try:
                value = float(match.group("number"))
            except ValueError:
                value = None
            unit = match.group("unit")
            if value is not None:
                liters = value
                if unit == "ML":
                    liters = value / 1000.0
                elif unit == "CL":
                    liters = value / 100.0

                liter_text = f"{liters:.2f}"
                add_variant(f"{liter_text} L")
                add_variant(f"{liter_text.replace('.', ',')} L")

                cl_value = int(round(liters * 100))
                ml_value = int(round(liters * 1000))
                if cl_value > 0:
                    add_variant(f"{cl_value} CL")
                if ml_value > 0:
                    add_variant(f"{ml_value} ML")

        return variants

    def _extract_tokens(self, descriptor: ProductDescriptor) -> List[str]:
        counter: Dict[str, float] = {}
        brand_norm = self._normalize(descriptor.brand)
        tracked_tokens: set[str] = set()

        raw_text = descriptor.raw_text
        if isinstance(raw_text, str) and len(raw_text) > 180:
            raw_text = " ".join(raw_text.split()[:40])

        def harvest(text: Optional[str], weight: float, *, primary: bool = False) -> None:
            if not text:
                return
            normalized_text = self._normalize(text)
            if not normalized_text:
                return
            for token in normalized_text.split():
                if not token or len(token) <= 2:
                    continue
                if token.isdigit():
                    continue
                if token in self.STOPWORDS:
                    continue
                if brand_norm and token == brand_norm:
                    continue
                counter[token] = counter.get(token, 0.0) + weight
                if primary:
                    tracked_tokens.add(token)

        harvest(descriptor.kind, 5.0, primary=True)
        harvest(descriptor.title, 4.0, primary=True)
        harvest(" ".join(descriptor.qualifiers), 3.0, primary=True)
        if raw_text:
            filtered = " ".join(tok for tok in self._normalize(raw_text).split() if tok in tracked_tokens)
            harvest(filtered, 0.5)
        ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        return [token for token, _score in ranked]

    def _build_query(self, parts: List[str]) -> Optional[str]:
        cleaned_parts = [re.sub(r"\s+", " ", part.strip()) for part in parts if part and part.strip()]
        if not cleaned_parts:
            return None
        candidate = " ".join(cleaned_parts)
        while len(candidate) > self.max_length and len(cleaned_parts) > 1:
            cleaned_parts.pop()
            candidate = " ".join(cleaned_parts)
        if len(candidate) > self.max_length:
            candidate = candidate[: self.max_length].rstrip()
        return candidate or None

    def make(self, d: ProductDescriptor) -> List[str]:
        brand = self._format_brand(d.brand)
        quantity_variants = self._expand_quantity_variants(d.qty)
        quantity_primary = quantity_variants[0] if quantity_variants else ""
        tokens = self._extract_tokens(d)
        tokens = self._reprioritize_tokens(tokens)

        # déduire s’il s’agit d’un paquet multi-articles (xN)
        has_multiplier = False
        if d.qty and isinstance(d.qty, str):
            if re.search(r"\b\d+\s*[x×]\s*\d+\b", d.qty.lower()):
                has_multiplier = True
        if d.title and isinstance(d.title, str) and not has_multiplier:
            if re.search(r"\b\d+\s*[x×]\s*\d+\b", d.title.lower()):
                has_multiplier = True
        if not has_multiplier and sum(1 for t in tokens if re.fullmatch(r"\d+", t)) > 1:
            has_multiplier = True
        qualifiers = [self._format_brand(q) for q in d.qualifiers if isinstance(q, str)]

        queries: List[str] = []
        seen: set[str] = set()

        def add_query(parts: List[str]) -> None:
            query = self._build_query(parts)
            if not query:
                return
            key = query.lower()
            if key in seen:
                return
            seen.add(key)
            queries.append(query)

        main_token = tokens[0] if tokens else ""
        secondary_token = tokens[1] if len(tokens) > 1 else ""
        tertiary_token = tokens[2] if len(tokens) > 2 else ""

        if brand and main_token and quantity_variants:
            for qty in quantity_variants:
                add_query([brand, main_token, qty])

        if brand and main_token and secondary_token:
            add_query([brand, main_token, secondary_token])

        if brand and quantity_variants:
            for qty in quantity_variants:
                add_query([brand, qty])

        if brand and tertiary_token and quantity_primary and len(queries) < self.max_keywords:
            add_query([brand, tertiary_token, quantity_primary])

        for qual in qualifiers:
            if brand and qual and quantity_primary:
                add_query([brand, qual, quantity_primary])
            elif brand and qual and main_token:
                add_query([brand, qual, main_token])

        if not queries and brand and main_token:
            add_query([brand, main_token])

        if not queries and main_token and quantity_primary:
            add_query([main_token, quantity_primary])

        if not queries and tokens:
            add_query(tokens[:3])

        if not queries and brand:
            add_query([brand])

        return queries[: self.max_keywords]

    def _reprioritize_tokens(self, tokens: List[str]) -> List[str]:
        if not tokens:
            return tokens

        def priority(token: str) -> tuple[int, int]:
            base = token.lower()
            if any(sub in base for sub in self.BOOST_SUBSTRINGS):
                return (0, -len(token))
            if base in self.GENERIC_TOKENS:
                return (2, len(token))
            return (1, -len(token))

        enumerated = list(enumerate(tokens))
        enumerated.sort(key=lambda item: (*priority(item[1]), item[0]))
        return [token for _, token in enumerated]
# ---------- Moteur de matching ----------
class MatchingEngine:
    def __init__(self, strict_qty: bool = True) -> None:
        self.strict_qty = strict_qty
    def score(self, src: ProductDescriptor, tgt: ProductDescriptor) -> float:
        score = 0.0
        # marque
        if src.brand and tgt.brand and self._norm(src.brand) == self._norm(tgt.brand):
            score += 0.4
        # type
        if src.kind and tgt.kind and self._norm(src.kind) in self._norm(tgt.raw_text):
            score += 0.3
        # quantité
        if src.qty and tgt.qty and self._norm(src.qty) == self._norm(tgt.qty):
            score += 0.2
        elif not self.strict_qty and src.qty and tgt.raw_text and self._norm(src.qty) in self._norm(tgt.raw_text):
            score += 0.1
        # pénalité si “bio” apparaît côté cible alors que pas côté source
        src_has_bio = any(self._norm(q) == "bio" for q in src.qualifiers) or " bio " in f" {self._norm(src.raw_text)} "
        tgt_has_bio = any(self._norm(q) == "bio" for q in tgt.qualifiers) or " bio " in f" {self._norm(tgt.raw_text)} "
        if tgt_has_bio and not src_has_bio:
            score -= 0.2
        return max(0.0, min(1.0, score))
    @staticmethod
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s.strip().lower())
    def is_match(self, src: ProductDescriptor, tgt: ProductDescriptor, threshold: float = 0.7) -> bool:
        return self.score(src, tgt) >= threshold
    def image_match(
        self,
        seed_url: Optional[str],
        candidate_url: Optional[str],
        provider: Optional[ImageCompareProvider] = None,
    ) -> bool:
        if provider:
            try:
                return bool(provider(seed_url, candidate_url))
            except Exception:
                pass
        # Placeholder : on vérifie simplement un token commun >= 4 caractères entre les deux URLs.
        if not seed_url or not candidate_url:
            return False
        seed_tokens = re.sub(r"[^a-z0-9]+", " ", seed_url.lower()).split()
        candidate_tokens = re.sub(r"[^a-z0-9]+", " ", candidate_url.lower()).split()
        common = {t for t in seed_tokens if len(t) >= 4} & {t for t in candidate_tokens if len(t) >= 4}
        return bool(common)
# ---------- Registre d’adapters (dans le dur) ----------
class CarrefourAdapter:
    name = "carrefour"
    supports_ean = True
    supports_keywords = False
    can_extract_ean_from_href = False
    # Implémentation réelle via subprocess car fetch_carrefour_price.py est complexe
    def search_by_ean(self, ean: str) -> Optional[ProductDescriptor]:
        # Carrefour logic now via standardized subprocess provider if patched
        # But we need to ensure it runs.
        # Let's use the helper directly here to be sure, using Market.
        # Re-using _make_subprocess_listing_provider logic logic
        
        prov = _make_subprocess_listing_provider("fetch_carrefour_price.py", "carrefour", {"STORE_QUERY": "Carrefour Market", "CARREFOUR_FRONTAL_STORE": ""})
        if prov:
             items = prov([ean])
             if items:
                 url, title, snippet = items[0]
                 return ProductDescriptor(
                    title=title,
                    ean=ean,
                    source=self.name,
                    raw_text=snippet,
                    seed_query=title,
                    leclerc_queries=[title]
                )
        return ProductDescriptor(ean=ean, source=self.name)
    def hard_validate(self, src: ProductDescriptor, url: str, pd: ProductDescriptor) -> Optional[float]:
        return None
    def override_threshold(self) -> Optional[float]:
        return None
    def override_strict_qty(self) -> Optional[bool]:
        return None
    def html(self) -> HtmlProvider | None:
        return None
    def image_compare(self) -> Optional[ImageCompareProvider]:
        return None
class AuchanAdapter:
    name = "auchan"
    supports_ean = True
    supports_keywords = True
    can_extract_ean_from_href = False

    def search_by_ean(self, ean: str) -> ProductDescriptor:
        prov = getattr(self, "_listing_provider", None)
        if not prov:
            return ProductDescriptor(ean=ean, source=self.name)
        
        items = prov([ean])
        if not items:
             return ProductDescriptor(ean=ean, source=self.name)
        
        url, title, snippet = items[0]
        
        return ProductDescriptor(
            title=title,
            ean=ean,
            source=self.name,
            raw_text=snippet,
            seed_query=title,
            leclerc_queries=[title]
        )
    def hard_validate(self, src: ProductDescriptor, url: str, pd: ProductDescriptor) -> Optional[float]:
        return None
    def override_threshold(self) -> Optional[float]:
        return None
    def override_strict_qty(self) -> Optional[bool]:
        return None
    def html(self) -> HtmlProvider | None:
        return None
    def image_compare(self) -> Optional[ImageCompareProvider]:
        return None
class MonoprixAdapter:
    name = "monoprix"
    supports_ean = True
    supports_keywords = True
    can_extract_ean_from_href = False
    _image_provider: Optional[ImageCompareProvider] = None

    def search_by_ean(self, ean: str) -> ProductDescriptor:
        prov = getattr(self, "_listing_provider", None)
        if not prov:
            return ProductDescriptor(ean=ean, source=self.name)
        
        items = prov([ean])
        if not items:
             return ProductDescriptor(ean=ean, source=self.name)
        
        url, title, snippet = items[0]
        
        return ProductDescriptor(
            title=title,
            ean=ean,
            source=self.name,
            raw_text=snippet,
            seed_query=title,
            leclerc_queries=[title]
        )
    def override_threshold(self) -> Optional[float]:
        return 0.75
    def override_strict_qty(self) -> Optional[bool]:
        return True
    def html(self) -> HtmlProvider | None:
        return getattr(self, "_html_provider", None)
    def image_compare(self) -> Optional[ImageCompareProvider]:
        return getattr(self, "_image_provider", None)
    def search_by_keywords(self, keywords: List[str]) -> List[str]:
        raise NotImplementedError
    def parse_product_page(self, url: str) -> Optional[ProductDescriptor]:
        raise NotImplementedError
    def hard_validate(self, src: ProductDescriptor, url: str, pd: ProductDescriptor) -> Optional[float]:
        # Validation renforcée appliquée niveau pipeline (texte + image)
        return None
class IntermarcheAdapter:
    name = "intermarche"
    supports_ean = True
    supports_keywords = True
    can_extract_ean_from_href = True
    
    def search_by_ean(self, ean: str) -> ProductDescriptor:
        prov = getattr(self, "_listing_provider", None)
        if not prov:
            return ProductDescriptor(ean=ean, source=self.name)
        
        items = prov([ean])
        if not items:
             return ProductDescriptor(ean=ean, source=self.name)
        
        url, title, snippet = items[0]
        
        return ProductDescriptor(
            title=title,
            ean=ean,
            source=self.name,
            raw_text=snippet,
            seed_query=title,
            leclerc_queries=[title]
        )

    def override_threshold(self) -> Optional[float]:
        return 0.7
    def override_strict_qty(self) -> Optional[bool]:
        return True
    def html(self) -> HtmlProvider | None:
        return getattr(self, "_html_provider", None)
    def image_compare(self) -> Optional[ImageCompareProvider]:
        return None
    def search_by_keywords(self, keywords: List[str]) -> List[str]:
        raise NotImplementedError
    def parse_product_page(self, url: str) -> Optional[ProductDescriptor]:
        raise NotImplementedError
    def hard_validate(self, src: ProductDescriptor, url: str, pd: ProductDescriptor) -> Optional[float]:
        if not src.ean:
            return None
        m = re.search(r"\b(\d{8,14})\b", url or "")
        if m:
            pd.ean = m.group(1)
            if pd.ean == src.ean:
                return 1.0
        return None
class LeclercAdapter:
    name = "leclerc"
    supports_ean = True  # Changed to True
    supports_keywords = True
    can_extract_ean_from_href = False

    def search_by_ean(self, ean: str) -> ProductDescriptor:
        prov = getattr(self, "_listing_provider", None)
        if not prov:
            return ProductDescriptor(ean=ean, source="leclerc")
        
        # Search EAN
        # The provider (agentic loop) will try the EAN
        # We treat EAN as a keyword here
        items = prov([ean])
        if not items:
             # Return empty-ish descriptor so pipeline knows we tried but failed
             return ProductDescriptor(ean=ean, source="leclerc")
        
        # Pick first result
        url, title, snippet = items[0]
        
        # Return basics (enough for seeding other search queries)
        return ProductDescriptor(
            title=title,
            ean=ean,
            source="leclerc",
            raw_text=snippet,
            seed_query=title, # Important for keyword generation
            leclerc_queries=[title]
        )

    def _listing_image_for(self, url: str) -> Optional[str]:
        return _lookup_leclerc_listing_image(url)
    def override_threshold(self) -> Optional[float]:
        return 0.7
    def override_strict_qty(self) -> Optional[bool]:
        return True
    def html(self) -> HtmlProvider | None:
        return getattr(self, "_html_provider", None)
    def search_by_keywords(self, keywords: List[str]) -> List[str]:
        raise NotImplementedError
    def parse_product_page(self, url: str) -> Optional[ProductDescriptor]:
        raise NotImplementedError
    def find_info_link(self, product_url: str) -> Optional[str]:
        get_html = self.html()
        if not get_html:
            return None
        html = get_html(product_url) or ""
        if not html:
            return None
        # ancre textuelle “Informations pratiques”
        for match in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, flags=re.I | re.S):
            href, text = match.group(1), match.group(2) or ""
            txt = re.sub(r"<[^>]+>", " ", text).strip().lower()
            if "information" in txt and "pratique" in txt:
                if href.lower().startswith("javascript:") or href.strip() == "#":
                    continue
                return self._absolutize(product_url, href)
        # fallback sur motif URL
        for match in re.finditer(r'href="([^"]+)"', html, flags=re.I):
            href = match.group(1)
            href_lc = href.lower()
            if any(key in href_lc for key in ["information", "fiche", "caracteristique", "pratique"]):
                if href_lc.startswith("javascript:") or href.strip() == "#":
                    continue
                return self._absolutize(product_url, href)
        return None
    def extract_ean_from_info(self, info_url: str) -> Optional[str]:
        get_html = self.html()
        if not get_html:
            return None
        html = get_html(info_url) or ""
        if not html:
            return None
        # Recherche directe
        m = re.search(r"(?:gtin13|gtin|ean)[^0-9]{0,20}(\d{8,14})", html, flags=re.I)
        if m:
            return m.group(1)
        # Texte linéaire
        for match in re.finditer(r">([^<]{0,200})<", html, flags=re.I):
            txt = match.group(1)
            if re.search(r"\b(EAN|GTIN|Code[-\s]?barres)\b", txt, flags=re.I):
                m2 = re.search(r"\b(\d{8,14})\b", txt)
                if m2:
                    return m2.group(1)
        # JSON-LD
        for match in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, flags=re.I | re.S):
            body = match.group(1) or ""
            m3 = re.search(r'"(gtin13|gtin|ean)"\s*:\s*"(\d{8,14})"', body, flags=re.I)
            if m3:
                return m3.group(2)
        return None
    @staticmethod
    def _extract_ean_from_html(html: Optional[str], url: Optional[str] = None) -> Optional[str]:
        if not html:
            return None
        patterns = [
            r'"(?:gtin13|gtin|ean)"\s*:\s*"(\d{8,14})"',
            r">\s*(?:EAN|GTIN|Code(?:[-\s]?barres)?)\s*[:#]?\s*(\d{8,14})",
            r"data-(?:ean|productean|gtin)=\"?(\d{8,14})\"?",
        ]
        for raw in patterns:
            match = re.search(raw, html, flags=re.I)
            if match:
                return match.group(1)
        if url:
            match = re.search(r"(?<!\d)(\d{8,14})(?!\d)", url)
            if match:
                return match.group(1)
        match = re.search(r"(?<!\d)(\d{8,14})(?!\d)", html)
        if match:
            return match.group(1)
        return None
    @staticmethod
    def _absolutize(base: str, href: str) -> str:
        try:
            from urllib.parse import urljoin
            return urljoin(base, href)
        except Exception:
            return href
    def hard_validate(self, src: ProductDescriptor, url: str, pd: ProductDescriptor) -> Optional[float]:
        if not src.ean:
            return None
        info = self.find_info_link(url)
        if not info:
            get_html = self.html()
            ean = self._extract_ean_from_html(get_html(url) if get_html else None, url)
        else:
            ean = self.extract_ean_from_info(info)
            if not ean:
                get_html = self.html()
                ean = self._extract_ean_from_html(get_html(url) if get_html else None, url)
        if ean:
            pd.ean = ean
            if ean == src.ean:
                return 1.0
        elif src.image_url and pd.image_url:
            try:
                from .image_matching import compare_references
            except Exception:
                return None
            if compare_references(src.image_url, pd.image_url, threshold=16):
                pd.ean = src.ean
                return 0.92
        return None

LeclercAdapterBase = LeclercAdapter
IntermarcheAdapterBase = IntermarcheAdapter
IntermarcheAdapterBase.can_extract_ean_from_href = True
MonoprixAdapterBase = MonoprixAdapter

try:
    from .adapters_keyword_impl import (
        LeclercAdapter as _KeywordLeclercAdapter,
        IntermarcheAdapter as _KeywordIntermarcheAdapter,
        MonoprixAdapter as _KeywordMonoprixAdapter,
    )
except Exception:
    LeclercAdapter = LeclercAdapterBase
    IntermarcheAdapter = IntermarcheAdapterBase
    MonoprixAdapter = MonoprixAdapterBase
else:
    LeclercAdapter = _KeywordLeclercAdapter
    IntermarcheAdapter = _KeywordIntermarcheAdapter
    MonoprixAdapter = _KeywordMonoprixAdapter
class ChronodriveAdapter:
    name = "chronodrive"
    supports_ean = True
    supports_keywords = False
    can_extract_ean_from_href = False
    
    def search_by_ean(self, ean: str) -> ProductDescriptor:
        prov = getattr(self, "_listing_provider", None)
        if not prov:
            return ProductDescriptor(ean=ean, source=self.name)
        
        items = prov([ean])
        if not items:
             return ProductDescriptor(ean=ean, source=self.name)
        
        url, title, snippet = items[0]
        return ProductDescriptor(
            title=title,
            ean=ean,
            source=self.name,
            raw_text=snippet,
            seed_query=title,
            leclerc_queries=[title]
        )

    def hard_validate(self, src: ProductDescriptor, url: str, pd: ProductDescriptor) -> Optional[float]:
        return None
    def override_threshold(self) -> Optional[float]:
        return None
    def override_strict_qty(self) -> Optional[bool]:
        return None
    def html(self) -> HtmlProvider | None:
        return None
    def image_compare(self) -> Optional[ImageCompareProvider]:
        return None


class CoursesUAdapter:
    name = "courseu"
    supports_ean = True
    supports_keywords = False
    can_extract_ean_from_href = False

    def search_by_ean(self, ean: str) -> ProductDescriptor:
        prov = getattr(self, "_listing_provider", None)
        if not prov:
            return ProductDescriptor(ean=ean, source=self.name)
        
        items = prov([ean])
        if not items:
             return ProductDescriptor(ean=ean, source=self.name)
        
        url, title, snippet = items[0]
        
        return ProductDescriptor(
            title=title,
            ean=ean,
            source=self.name,
            raw_text=snippet,
            seed_query=title,
            leclerc_queries=[title]
        )

    def hard_validate(self, src: ProductDescriptor, url: str, pd: ProductDescriptor) -> Optional[float]:
        # Fix: Trust EAN match implicitly for strict stores
        if src.ean and pd.ean and src.ean == pd.ean:
            return 1.0
        return None

    def override_threshold(self) -> Optional[float]:
        return None

    def override_strict_qty(self) -> Optional[bool]:
        return None

    def html(self) -> HtmlProvider | None:
        return None

    def html(self) -> HtmlProvider | None:
        return None

    def image_compare(self) -> Optional[ImageCompareProvider]:
        return None


class CasinoAdapter:
    name = "casino"
    supports_ean = True
    supports_keywords = False
    can_extract_ean_from_href = True

    def search_by_ean(self, ean: str) -> ProductDescriptor:
        prov = getattr(self, "_listing_provider", None)
        if not prov:
            return ProductDescriptor(ean=ean, source=self.name)
        
        items = prov([ean])
        if not items:
             return ProductDescriptor(ean=ean, source=self.name)
        
        url, title, snippet = items[0]
        
        return ProductDescriptor(
            title=title,
            ean=ean,
            source=self.name,
            raw_text=snippet,
            seed_query=title,
            leclerc_queries=[title]
        )

    def hard_validate(self, src: ProductDescriptor, url: str, pd: ProductDescriptor) -> Optional[float]:
        return None
    def override_threshold(self) -> Optional[float]:
        return None
    def override_strict_qty(self) -> Optional[bool]:
        return None
    def html(self) -> HtmlProvider | None:
        return None
    def image_compare(self) -> Optional[ImageCompareProvider]:
        return None


class G20Adapter:
    name = "g20"
    supports_ean = True
    supports_keywords = False
    can_extract_ean_from_href = False
    
    def search_by_ean(self, ean: str) -> ProductDescriptor:
        prov = getattr(self, "_listing_provider", None)
        if not prov:
            return ProductDescriptor(ean=ean, source=self.name)
        
        items = prov([ean])
        if not items:
             return ProductDescriptor(ean=ean, source=self.name)
        
        url, title, snippet = items[0]
        return ProductDescriptor(
            title=title,
            ean=ean,
            source=self.name,
            raw_text=snippet,
            seed_query=title,
            leclerc_queries=[title]
        )

    def hard_validate(self, src: ProductDescriptor, url: str, pd: ProductDescriptor) -> Optional[float]:
        return None
    def override_threshold(self) -> Optional[float]:
        return None
    def override_strict_qty(self) -> Optional[bool]:
        return None
    def html(self) -> HtmlProvider | None:
        return None
    def image_compare(self) -> Optional[ImageCompareProvider]:
        return None

# Registres codés en dur. Ajouter un magasin = ajouter une classe + lister ici.
# Registres codés en dur. Ajouter un magasin = ajouter une classe + lister ici.
EAN_DIRECT_REGISTRY: List[type] = [
    CarrefourAdapter,
    AuchanAdapter,
    ChronodriveAdapter,
    LeclercAdapter,
    CoursesUAdapter,
    G20Adapter,
    MonoprixAdapter,
    CasinoAdapter,
    IntermarcheAdapter,
]
KEYWORD_REGISTRY: List[type] = [
    MonoprixAdapter,
    IntermarcheAdapter,
    LeclercAdapter,
    # autres à ajouter ici
]
# ---------- Pipeline principal ----------
@dataclass
class MatchResult:
    adapter: str
    url: str
    descriptor: ProductDescriptor
    score: float
@dataclass(frozen=True)
class AdapterPolicy:
    requires_ean: bool
    require_image_lock: bool
    disallow_packs: bool
    min_text_score: float
POLICIES: Dict[str, AdapterPolicy] = {
    "intermarche": AdapterPolicy(requires_ean=True, require_image_lock=False, disallow_packs=True, min_text_score=0.70),
    "casino": AdapterPolicy(requires_ean=True, require_image_lock=False, disallow_packs=True, min_text_score=0.70),
    "spar": AdapterPolicy(requires_ean=True, require_image_lock=False, disallow_packs=True, min_text_score=0.70),
    "leclerc": AdapterPolicy(requires_ean=False, require_image_lock=False, disallow_packs=True, min_text_score=0.70), # hard_validate handles logic
    "monoprix": AdapterPolicy(requires_ean=False, require_image_lock=True, disallow_packs=True, min_text_score=0.75),
}
@dataclass
class AuditEntry:
    adapter: str
    url: str
    base_score: float
    threshold_used: float
    image_pass: bool
    forced: Optional[float]
    reason: str
class FinderPipeline:
    _hooks_initialized = False

    def __init__(self) -> None:
        self.ensure_hooks()
        self.consolidator = Consolidator()
        self.matcher = MatchingEngine(strict_qty=True)
        self.keywords: List[str] = []
        self.audit: List[AuditEntry] = []
        self._monoprix_cache: List[str] = []

    @classmethod
    def ensure_hooks(cls) -> None:
        if cls._hooks_initialized:
            return
        try:
            html_provider = _make_leclerc_html_provider()
            if html_provider is not None:
                LeclercAdapter._html_provider = staticmethod(html_provider)  # type: ignore[attr-defined]
            listing_provider = _make_leclerc_listing_provider()
            if listing_provider is not None:
                LeclercAdapter._listing_provider = staticmethod(listing_provider)  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            image_provider = _make_monoprix_image_provider()
            if image_provider is not None:
                MonoprixAdapter._image_provider = image_provider  # type: ignore[attr-defined]
            listing_provider = _make_monoprix_listing_provider()
            if listing_provider is not None:
                MonoprixAdapter._listing_provider = staticmethod(listing_provider)  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            # Replace manual providers with subprocess ones where available
            
            # Carrefour Market (Specific)
            carrefour_provider = _make_subprocess_listing_provider("fetch_carrefour_price.py", "carrefour", {"STORE_QUERY": "Carrefour Market", "CARREFOUR_FRONTAL_STORE": ""})
            if carrefour_provider:
                 # We patch the class logic directly or use hook? 
                 # CarrefourAdapter has custom search_by_ean, we will update it to standard pattern
                 # But we can also set the provider and let adapter use it if we standardized Adapter code.
                 # Currently CarrefourAdapter.search_by_ean is custom. 
                 pass

            # Auchan
            auchan_provider = _make_subprocess_listing_provider("fetch_auchan_price.py", "auchan")
            if auchan_provider:
                AuchanAdapter._listing_provider = staticmethod(auchan_provider)

            # Courses U
            u_provider = _make_subprocess_listing_provider("fetch_courseu_price.py", "courseu")
            if u_provider:
                CoursesUAdapter._listing_provider = staticmethod(u_provider)

            # Intermarché
            inter_provider = _make_subprocess_listing_provider("fetch_intermarche_price.py", "intermarche")
            if inter_provider:
                IntermarcheAdapter._listing_provider = staticmethod(inter_provider)

            # Casino
            casino_provider = _make_subprocess_listing_provider("fetch_casino_price.py", "casino")
            if casino_provider:
                CasinoAdapter._listing_provider = staticmethod(casino_provider)
            
            # Chronodrive
            chrono_provider = _make_subprocess_listing_provider("fetch_chronodrive_price.py", "chronodrive")
            if chrono_provider:
                ChronodriveAdapter._listing_provider = staticmethod(chrono_provider)
                
            # G20
            g20_provider = _make_subprocess_listing_provider("fetch_g20_price.py", "g20")
            if g20_provider:
                G20Adapter._listing_provider = staticmethod(g20_provider)
        except Exception:
            pass
        cls._hooks_initialized = True
    def _policy(self, adapter_name: str) -> AdapterPolicy:
        return POLICIES.get(adapter_name, AdapterPolicy(True, False, True, 0.70))
    # Étape A: collecter depuis sites EAN-direct
    def collect_from_ean_sites(self, ean: str) -> ProductDescriptor:
        # 0. Seed from Descriptor Store (Manual/Seed Catalog)
        base_data = get_descriptor(ean)
        if base_data:
             if "name" in base_data and "title" not in base_data:
                 base_data["title"] = base_data.pop("name")
             # Clean unknown keys
             valid_keys = {"title", "brand", "qty", "ean", "image_url", "source", "seed_query", "raw_text"}
             clean_data = {k: v for k, v in base_data.items() if k in valid_keys}
             self.consolidator.add(ProductDescriptor(**clean_data))

        # 1. Try Store Adapters
        for cls in EAN_DIRECT_REGISTRY:
            adapter = cls()
            assert getattr(adapter, "supports_ean", False) is True
            try:
                pd = adapter.search_by_ean(ean)
                self.consolidator.add(pd)
            except NotImplementedError:
                continue
        
        # 2. OpenFoodFacts Fallback (if no title found yet)
        consolidated = self.consolidator.merged()
        if not consolidated.title:
            # OpenFoodFacts DISABLED per user request.
            # We strictly rely on store adapters.
            pass

        consolidated = self.consolidator.merged()
        if not consolidated.ean:
            consolidated.ean = ean
        return consolidated
    # Étape B: générer mots-clés
    def generate_keywords(self, consolidated: ProductDescriptor) -> List[str]:
        base_text = (
            consolidated.seed_query
            or consolidated.title
            or consolidated.raw_text
            or consolidated.brand
            or ""
        ).strip()
        tokens = base_text.split()
        priority_keywords: List[str] = []
        if len(tokens) >= 4:
            priority_keywords.append(" ".join(tokens[:4]))
        if len(tokens) >= 3:
            priority_keywords.append(" ".join(tokens[:3]))
        if not priority_keywords and tokens:
            priority_keywords.append(" ".join(tokens))

        heuristic_keywords = KeywordGenerator(max_keywords=4).make(consolidated)
        ai_keywords: List[str] = []
        if USE_AI_ASSIST and suggest_search_queries:
            profile = {
                "title": consolidated.title,
                "brand": consolidated.brand,
                "quantity": consolidated.qty,
                "qualifiers": consolidated.qualifiers,
                "ean": consolidated.ean,
                "seed_query": consolidated.seed_query,
                "raw_text": consolidated.raw_text,
            }
            try:
                # We target 'leclerc' as the most restrictive engine to ensure high quality queries
                resp = suggest_search_queries(
                    profile,
                    descriptor=asdict(consolidated),
                    max_queries=5,
                    store="leclerc",
                    max_length=32,
                )
                # Prioritize structured response
                structured = resp.data.get("structured")
                if isinstance(structured, dict):
                    if structured.get("golden"):
                        ai_keywords.append(structured["golden"])
                    if structured.get("fallback_specific"):
                        ai_keywords.append(structured["fallback_specific"])
                    if structured.get("fallback_broad"):
                        ai_keywords.append(structured["fallback_broad"])
                
                # Fallback to list if structured is empty
                if not ai_keywords:
                    queries = resp.data.get("queries") if isinstance(resp.data, dict) else None
                    if isinstance(queries, list):
                        ai_keywords = [q for q in queries if isinstance(q, str) and q.strip()]
            except Exception:
                ai_keywords = []

        merged: List[str] = []
        seen: set[str] = set()

        def push(seq: List[str]):
            for item in seq:
                value = " ".join(item.split())
                if not value:
                    continue
                key = value.lower()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(value)

        # Priority: AI Golden > Manual Priority > Heuristic
        push(ai_keywords)
        push(priority_keywords)
        push(heuristic_keywords)
        self.keywords = merged[:8]
        if not self.keywords:
            fallback = self._fallback_keywords_from_summary(consolidated.ean)
            if fallback:
                self.keywords.extend(fallback)
        
        return self.keywords

    def _fallback_keywords_from_summary(self, ean: Optional[str]) -> List[str]:
        if not ean:
            return []
        summary_path = Path(os.environ.get("RESULTS_DIR") or "/Users/laurentpoupet/Sites/maxicourses-ovh/www/maxicourses_test/results") / "summary.json"
        if not summary_path.exists():
            return []
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        block = data.get(str(ean))
        if not isinstance(block, dict):
            return []
        titles: List[str] = []
        brands: List[str] = []
        for entry in block.values():
            if not isinstance(entry, dict):
                continue
            payload = entry.get("payload")
            if not isinstance(payload, dict):
                continue
            t = payload.get("title") or payload.get("product_name")
            product_obj = payload.get("product") or {}
            b = payload.get("brand") or product_obj.get("brand")
            if isinstance(t, str) and t.strip():
                titles.append(t.strip())
            if isinstance(b, str) and b.strip():
                brands.append(b.strip())
            if not b and isinstance(t, str) and t.strip():
                inferred = _infer_brand_from_title(t)
                if inferred:
                    brands.append(inferred)
        title = titles[0] if titles else ""
        brand = brands[0] if brands else ""
        tokens = []
        norm = re.sub(r"[^a-z0-9]+", " ", title.lower())
        for tok in norm.split():
            if re.search(r"\d", tok):
                continue
            if tok in {"ml", "l", "cl", "kg", "g", "gr", "litre", "litres"}:
                continue
            if tok and tok not in tokens:
                tokens.append(tok)
        main = tokens[0] if tokens else ""
        candidates = []
        if brand and main:
            candidates.append(f"{brand} {main}")
        if title:
            candidates.append(title)
        if main:
            candidates.append(main)
        seen: set[str] = set()
        filtered: List[str] = []
        for q in candidates:
            key = q.lower().strip()
            if not key or key in seen:
                continue
            seen.add(key)
            filtered.append(q)
        return filtered[:3]
    
    def _monoprix_keywords(self, consolidated: ProductDescriptor) -> List[str]:
        """
        Requêtes Monoprix sans quantités pour éviter les listings trop larges.
        """
        filtered: List[str] = []
        seen: set[str] = set()
        unit_tokens = {"ml", "l", "cl", "kg", "g", "gr", "kg.", "l.", "ml.", "cl.", "litre", "litres"}
    
        def strip_qty(query: str) -> Optional[str]:
            tokens: List[str] = []
            for tok in query.split():
                low = tok.lower().strip()
                if re.search(r"\d", low):
                    continue
                if low in unit_tokens:
                    continue
                tokens.append(tok)
            cleaned = " ".join(tokens).strip()
            return cleaned or None
    
        for q in self.keywords:
            cleaned = strip_qty(q)
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            filtered.append(cleaned)
    
        if not filtered:
            brand = (consolidated.brand or "").strip()
            title_tokens: List[str] = []
            norm_title = re.sub(r"[^a-z0-9]+", " ", (consolidated.title or "").lower())
            for tok in norm_title.split():
                if tok in unit_tokens or re.search(r"\d", tok):
                    continue
                if tok and tok not in title_tokens:
                    title_tokens.append(tok)
            main_token = title_tokens[0] if title_tokens else ""
            if brand and main_token:
                filtered.append(f"{brand} {main_token}")
            elif main_token:
                filtered.append(main_token)
            elif brand:
                filtered.append(brand)
        return filtered
    
    def search_on_keyword_sites(self, consolidated: ProductDescriptor) -> List[MatchResult]:
        self.ensure_hooks()
        results: List[MatchResult] = []
        orig_strict = self.matcher.strict_qty
        for cls in KEYWORD_REGISTRY:
            adapter = cls()
            assert getattr(adapter, "supports_keywords", False) is True
            policy = self._policy(adapter.name)
            try:
                override_strict = adapter.override_strict_qty()
                if override_strict is not None:
                    self.matcher.strict_qty = bool(override_strict)
                if adapter.name == "leclerc" and consolidated.leclerc_queries:
                    urls = adapter.search_by_keywords(consolidated.leclerc_queries)
                elif adapter.name == "monoprix":
                    urls = []
                    mono_queries = self._monoprix_keywords(consolidated)
                    for q in mono_queries:
                        attempt_urls = adapter.search_by_keywords([q])
                        if attempt_urls:
                            urls.extend(attempt_urls)
                            break
                else:
                    urls = adapter.search_by_keywords(self.keywords)
                for url in urls:
                    pd = adapter.parse_product_page(url)
                    if not pd:
                        continue
                    if getattr(adapter, "can_extract_ean_from_href", False):
                        m = re.search(r"(\d{8,14})", (url or ""))
                        if m and not pd.ean:
                            pd.ean = m.group(1)
                        if pd.ean:
                            self.consolidator.add(pd)
                    provider: Optional[ImageCompareProvider] = None
                    if hasattr(adapter, "image_compare"):
                        try:
                            provider = adapter.image_compare()
                        except Exception:
                            provider = None
                    if policy.disallow_packs and is_pack_or_bundle(pd.title, pd.raw_text):
                        self.audit.append(
                            AuditEntry(
                                adapter=adapter.name,
                                url=url,
                                base_score=0.0,
                                threshold_used=policy.min_text_score,
                                image_pass=False,
                                forced=None,
                                reason="filtered_pack",
                            )
                        )
                        continue
                    forced = adapter.hard_validate(consolidated, url, pd)
                    if forced is not None:
                        if policy.requires_ean and not pd.ean:
                            self.audit.append(
                                AuditEntry(
                                    adapter=adapter.name,
                                    url=url,
                                    base_score=1.0,
                                    threshold_used=policy.min_text_score,
                                    image_pass=False,
                                    forced=float(forced),
                                    reason="forced_but_missing_ean",
                                )
                            )
                            continue
                        results.append(MatchResult(adapter=adapter.name, url=url, descriptor=pd, score=float(forced)))
                        self.audit.append(
                            AuditEntry(
                                adapter=adapter.name,
                                url=url,
                                base_score=1.0,
                                threshold_used=policy.min_text_score,
                                image_pass=False,
                                forced=float(forced),
                                reason="hard_validate",
                            )
                        )
                        continue
                    base_score = self.matcher.score(consolidated, pd)
                    img_pass = True
                    if policy.require_image_lock:
                        img_pass = self.matcher.image_match(
                            consolidated.image_url,
                            pd.image_url,
                            provider=provider,
                        )
                        if not img_pass:
                            self.audit.append(
                                AuditEntry(
                                    adapter=adapter.name,
                                    url=url,
                                    base_score=base_score,
                                    threshold_used=policy.min_text_score,
                                    image_pass=False,
                                    forced=None,
                                    reason="image_lock_failed",
                                )
                            )
                            continue
                    meets_text_threshold = base_score >= policy.min_text_score
                    if not meets_text_threshold and not (policy.require_image_lock and img_pass):
                        self.audit.append(
                            AuditEntry(
                                adapter=adapter.name,
                                url=url,
                                base_score=base_score,
                                threshold_used=policy.min_text_score,
                                image_pass=img_pass,
                                forced=None,
                                reason="below_text_threshold",
                            )
                        )
                        continue
                    if policy.requires_ean and not pd.ean:
                        self.audit.append(
                            AuditEntry(
                                adapter=adapter.name,
                                url=url,
                                base_score=base_score,
                                threshold_used=policy.min_text_score,
                                image_pass=img_pass,
                                forced=None,
                                reason="missing_ean_required",
                            )
                        )
                        continue
                    final_score = base_score
                    audit_reason = "generic"
                    if policy.require_image_lock and img_pass and not meets_text_threshold:
                        final_score = max(final_score, policy.min_text_score)
                        audit_reason = "image_override"
                    if adapter.name == "monoprix" and img_pass:
                        final_score = max(final_score, 0.995)
                        audit_reason = "mono_image_override" if audit_reason == "image_override" else "mono_text+image"
                    results.append(MatchResult(adapter=adapter.name, url=url, descriptor=pd, score=final_score))
                    self.audit.append(
                        AuditEntry(
                            adapter=adapter.name,
                            url=url,
                            base_score=base_score,
                            threshold_used=policy.min_text_score,
                            image_pass=img_pass,
                            forced=None,
                            reason=audit_reason,
                        )
                    )
            except NotImplementedError:
                continue
            finally:
                self.matcher.strict_qty = orig_strict
            results.sort(key=lambda r: -r.score)
            return results
    
        # Étape D: décision
    def decide(self, consolidated: ProductDescriptor, candidates: List[MatchResult], threshold: float = 0.7
               ) -> Optional[MatchResult]:
        self.ensure_hooks()
        for c in candidates:
            policy = self._policy(c.adapter)
            thr = max(threshold, policy.min_text_score)
            if policy.requires_ean and not c.descriptor.ean:
                continue
            if c.score >= 0.99 or self.matcher.is_match(consolidated, c.descriptor, threshold=thr):
                return c
        
        # Fallback: AI Smart Substitution
        # If no classic match found, ask AI to pick a good substitute among candidates
        try:
            from ai_helpers import suggest_equivalent, USE_AI_ASSIST
            if USE_AI_ASSIST and candidates:
                # Filter candidates to avoid sending garbage (keep decent potential matches)
                # Lower threshold for AI consideration
                ai_input_candidates = []
                for c in candidates:
                    if c.score < 0.25:  # Basic sanity filter
                        continue
                    ai_input_candidates.append({
                        "title": c.descriptor.title,
                        "brand": c.descriptor.brand,
                        "kind": c.descriptor.kind,
                        "qty": c.descriptor.qty,
                        "qualifiers": c.descriptor.qualifiers,
                        "ean": c.descriptor.ean,
                        "image_url": c.descriptor.image_url,
                        "source": c.descriptor.source,
                        "raw_text": c.descriptor.raw_text,
                        "url": c.url,
                        "price": c.descriptor.price,
                        "quantity": c.descriptor.quantity,
                        "score": c.score,
                        "adapter": c.adapter
                    })
                
                if ai_input_candidates:
                    # Consolidated descriptor to dict for AI
                    profile = asdict(consolidated)
                    print(f"[DEBUG] Finder AI Substitution: Asking AI to choose among {len(ai_input_candidates)} candidates...", file=sys.stderr)
                    resp = suggest_equivalent(profile, ai_input_candidates)
                    
                    if resp.status == "ok" and resp.data.get("equivalent"):
                        eq = resp.data["equivalent"]
                        reason = eq.get("reason", "Selected by AI")
                        title_match = eq.get("title")
                        
                        # Find back the MatchResult
                        chosen = next(
                            (c for c in candidates if (c.descriptor.title == title_match or c.descriptor.title == title_match)), 
                            None
                        )
                        if chosen:
                            print(f"[DEBUG] Finder AI Substitution: AI selected '{title_match}' ({reason})", file=sys.stderr)
                            # Mark as substitute in note
                            note = chosen.descriptor.note or ""
                            if "Produit différent" not in note:
                                sep = " | " if note else ""
                                chosen.descriptor.note = f"{note}{sep}Produit différent (AI): {reason}"
                            # Return this candidate
                            return chosen
                    else:
                        print(f"[DEBUG] Finder AI Substitution: No equivalent found by AI.", file=sys.stderr)

        except ImportError:
            pass
        except Exception as e:
            print(f"[DEBUG] Finder AI Substitution Error: {e}", file=sys.stderr)

        return None
# ---------- API haut niveau ----------
def find_equivalents(ean: str, threshold: float = 0.7) -> Tuple[ProductDescriptor, List[str], List[MatchResult], Optional[MatchResult]]:
    pipeline = FinderPipeline()
    consolidated = pipeline.collect_from_ean_sites(ean)
    
    # [NEW] Upsert Golden Record (Initial)
    try:
        from .repository import ProductRepository
        repo = ProductRepository()
    except ImportError:
        repo = None

    if repo and consolidated and consolidated.ean:
        repo.upsert_product(
            ean=consolidated.ean, 
            data=asdict(consolidated),
            source="consolidated_init"
        )

    keywords = pipeline.generate_keywords(consolidated)
    candidates = pipeline.search_on_keyword_sites(consolidated)
    decision = pipeline.decide(consolidated, candidates, threshold=threshold)

    # [NEW] Upsert Golden Record (Final Decision)
    if repo and decision and decision.descriptor.ean:
         repo.upsert_product(
            ean=decision.descriptor.ean,
            data=asdict(decision.descriptor),
            source=decision.adapter
         )
         
    return consolidated, keywords, candidates, decision
# ---------- Exécution de test manuelle ----------
def _cli() -> None:
    parser = argparse.ArgumentParser(description="Finder pipeline debug")
    parser.add_argument("--ean", required=False, help="EAN à analyser (13 chiffres)")
    parser.add_argument("--threshold", type=float, default=0.7, help="Seuil de matching")
    parser.add_argument("--dump", action="store_true", help="Affiche les détails")
    args = parser.parse_args()
    ean = re.sub(r"\D", "", args.ean or "")
    if len(ean) != 13:
        raise SystemExit("[finder] EAN invalide")
    consolidated, keywords, candidates, decision = find_equivalents(ean, threshold=args.threshold)
    print("[Consolidated]", consolidated)
    print("[Keywords]", keywords)
    if args.dump:
        print("[Candidates top 5]", [(c.adapter, round(c.score, 3), c.url) for c in candidates[:5]])
        print("[Decision]", (decision.adapter, decision.url, round(decision.score, 3)) if decision else None)


if __name__ == "__main__":
    _cli()
