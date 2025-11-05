# maxicourses_test/pipeline/adapters_keyword_impl.py
# Implémentations “dans le dur” pour sites sans recherche EAN directe.
# Règle:
# - Leclerc: ouvre jusqu’à 10 fiches, valide si EAN trouvé dans “Informations pratiques”.
# - Intermarché: ouvre jusqu’à 10 fiches, valide si EAN présent dans l’URL (HREF).
# - Monoprix: ouvre jusqu’à 10 fiches, valide si descriptif proche et image proche de la seed.

from __future__ import annotations
import re
from typing import List, Optional, Callable, Tuple

# Interfaces et modèles importés du finder
from .finder import ProductDescriptor
from .finder import LeclercAdapter as _LeclercBase
from .finder import IntermarcheAdapter as _InterBase
from .finder import MonoprixAdapter as _MonoBase

# Utilitaires partagés
MAX_CANDIDATES = 10


def _score_listing_line(title: str, snippet: str, kw: List[str]) -> float:
    t = f"{title or ''} {snippet or ''}".lower()
    hits = sum(1 for k in kw if k and k.lower() in t)
    return hits / max(len([k for k in kw if k]), 1)


def _clean(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


# -----------------------------
# Leclerc
# -----------------------------
class LeclercAdapter(_LeclercBase):
    """
    Recherche par mots clés. Prend les 10 meilleurs candidats du listing.
    parse_product_page: lit la fiche, puis suit “Informations pratiques” via provider HTML
    pour extraire l’EAN. Retourne un ProductDescriptor complet.
    """

    # Ces deux providers sont branchés automatiquement par Finder.ensure_hooks()
    #   - html_provider(url) -> str|None
    #   - image_compare(seed_url, cand_url) -> bool (non utilisé ici)
    def html(self):
        return getattr(self, "_html_provider", None)

    def _search_listing(self, keywords: List[str]) -> List[Tuple[str, str, str]]:
        """
        Retourne une liste [(url, title, snippet)] depuis la page résultats.
        Ici on délègue la navigation Playwright au fetcher déjà branché par Finder.
        """
        prov: Optional[Callable[[List[str]], List[Tuple[str, str, str]]]] = getattr(self, "_listing_provider", None)
        items = prov(keywords) if prov else []
        # Trie par recouvrement de mots-clés et limite
        items.sort(key=lambda it: -_score_listing_line(it[1], it[2], keywords))
        return items[:MAX_CANDIDATES]

    def search_by_keywords(self, keywords: List[str]) -> List[str]:
        return [u for (u, _t, _s) in self._search_listing(keywords)]

    def parse_product_page(self, url: str) -> Optional[ProductDescriptor]:
        get_html = self.html()
        if not get_html:
            return None
        html = get_html(url) or ""
        title = _clean(re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.I | re.S).group(1)) if re.search(r"<h1", html, re.I) else ""
        # Image principale si dispo
        mimg = re.search(r'<img[^>]+class="[^"]*product[^"]*"[^>]+src="([^"]+)"', html, flags=re.I)
        image_url = mimg.group(1) if mimg else None

        # Utilise les helpers du base class pour trouver le lien “Informations pratiques” puis extraire l’EAN
        ean = None
        info = self.find_info_link(url)
        if info:
            ean = self.extract_ean_from_info(info)
        if not ean:
            ean = self._extract_ean_from_html(html, url)

        # Remplissage descriptor sans fiction
        pd = ProductDescriptor(
            title=title,
            brand="",
            kind="",
            qty="",
            qualifiers=[],
            ean=ean,
            image_url=image_url,
            source="leclerc",
            raw_text=html[:4000],
        )
        return pd


# -----------------------------
# Intermarché
# -----------------------------
class IntermarcheAdapter(_InterBase):
    """
    Recherche par mots clés. Prend les 10 meilleurs candidats du listing.
    parse_product_page: ouvre chaque URL; EAN validé s’il est dans l’URL.
    """

    def html(self):
        return getattr(self, "_html_provider", None)  # optionnel pour extractions supplémentaires

    def _search_listing(self, keywords: List[str]) -> List[Tuple[str, str, str]]:
        prov: Optional[Callable[[List[str]], List[Tuple[str, str, str]]]] = getattr(self, "_listing_provider", None)
        items = prov(keywords) if prov else []
        items.sort(key=lambda it: -_score_listing_line(it[1], it[2], keywords))
        return items[:MAX_CANDIDATES]

    def search_by_keywords(self, keywords: List[str]) -> List[str]:
        return [u for (u, _t, _s) in self._search_listing(keywords)]

    def parse_product_page(self, url: str) -> Optional[ProductDescriptor]:
        # EAN dans l’HREF = critère fort. Finder appliquera hard_validate==1.0 si égal seed.
        m = re.search(r"\b(\d{8,14})\b", url)
        found_ean = m.group(1) if m else None

        # Option: extraire titre/image via provider HTML si disponible
        html = ""
        get_html = self.html()
        if get_html:
            html = get_html(url) or ""
        title = _clean(re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.I | re.S).group(1)) if html and re.search(r"<h1", html, re.I) else ""
        mimg = re.search(r'<img[^>]+class="[^"]*product[^"]*"[^>]+src="([^"]+)"', html, flags=re.I) if html else None
        image_url = mimg.group(1) if mimg else None

        pd = ProductDescriptor(
            title=title,
            brand="",
            kind="",
            qty="",
            qualifiers=[],
            ean=found_ean,
            image_url=image_url,
            source="intermarche",
            raw_text=html[:4000] if html else "",
        )
        return pd


# -----------------------------
# Monoprix
# -----------------------------
class MonoprixAdapter(_MonoBase):
    """
    Recherche par mots clés. Prend les 10 meilleurs candidats du listing.
    parse_product_page: extrait descriptif et image. Finder exigera image proche de la seed.
    """

    def html(self):
        return getattr(self, "_html_provider", None)  # optionnel

    def image_compare(self):
        # Fournie par Finder.ensure_hooks() ; comparaison pHash Playwright.
        return getattr(self, "_image_provider", None)

    def _search_listing(self, keywords: List[str]) -> List[Tuple[str, str, str]]:
        prov: Optional[Callable[[List[str]], List[Tuple[str, str, str]]]] = getattr(self, "_listing_provider", None)
        items = prov(keywords) if prov else []
        items.sort(key=lambda it: -_score_listing_line(it[1], it[2], keywords))
        return items[:MAX_CANDIDATES]

    def search_by_keywords(self, keywords: List[str]) -> List[str]:
        return [u for (u, _t, _s) in self._search_listing(keywords)]

    def parse_product_page(self, url: str) -> Optional[ProductDescriptor]:
        get_html = self.html()
        html = get_html(url) if get_html else None
        html = html or ""
        title = _clean(re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.I | re.S).group(1)) if re.search(r"<h1", html, re.I) else ""
        # Image
        mimg = re.search(r'<img[^>]+src="([^"]+)"[^>]*class="[^"]*(?:product|main)[^"]*"', html, flags=re.I)
        image_url = mimg.group(1) if mimg else None

        # Pas d’EAN exposé chez Monoprix
        pd = ProductDescriptor(
            title=title,
            brand="",
            kind="",
            qty="",
            qualifiers=[],
            ean=None,
            image_url=image_url,
            source="monoprix",
            raw_text=html[:4000],
        )
        return pd
