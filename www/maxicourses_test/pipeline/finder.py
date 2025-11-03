# finder.py
# Étape 1/3 — Scaffold solide et extensible, 100% code “dans le dur”.
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Iterable, Optional, Tuple, Protocol, Callable
import re
import math

HtmlProvider = Callable[[str], Optional[str]]
ImageCompareProvider = Callable[[Optional[str], Optional[str]], bool]

# ---------- Modèle ----------
@dataclass
class ProductDescriptor:
    title: str = ""
    brand: str = ""
    kind: str = ""            # ex: "miel de fleurs"
    qty: str = ""             # ex: "500 g" ou "1,75 L"
    qualifiers: List[str] = field(default_factory=list)  # ex: ["bio", "sans sucre"]
    ean: Optional[str] = None
    image_url: Optional[str] = None
    source: str = ""          # nom d’enseigne adapter
    raw_text: str = ""        # descriptif long brut pour matching

    def tokens(self) -> List[str]:
        txt = " ".join([self.title, self.brand, self.kind, self.qty, " ".join(self.qualifiers), self.raw_text])
        txt = re.sub(r"[^a-z0-9àâçéèêëîïôûùüÿœ\s\-\.]", " ", txt.lower())
        return [t for t in re.split(r"\s+", txt) if t]

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
        def pick(field: str) -> str:
            vals = [getattr(s, field) for s in self.sources if getattr(s, field)]
            if not vals:
                return ""
            # mode
            scores: Dict[str, int] = {}
            for v in vals:
                scores[v] = scores.get(v, 0) + 1
            return max(scores.items(), key=lambda kv: kv[1])[0]

        merged = ProductDescriptor(
            title=pick("title"),
            brand=pick("brand"),
            kind=pick("kind"),
            qty=pick("qty"),
            ean=next((s.ean for s in self.sources if s.ean), None),
            image_url=next((s.image_url for s in self.sources if s.image_url), None),
            source="consolidated",
            raw_text=" ".join([s.raw_text for s in self.sources if s.raw_text]),
        )
        # qualifiers: union pondérée
        q_all: Dict[str, int] = {}
        for s in self.sources:
            for q in s.qualifiers:
                q_all[q] = q_all.get(q, 0) + 1
        merged.qualifiers = [q for q, _n in sorted(q_all.items(), key=lambda kv: -kv[1])]
        return merged

# ---------- Générateur de mots-clés ----------
class KeywordGenerator:
    def __init__(self, max_keywords: int = 4) -> None:
        self.max_keywords = max_keywords

    def make(self, d: ProductDescriptor) -> List[str]:
        # Heuristique simple, stable et lisible
        candidates: List[str] = []
        if d.brand:
            candidates.append(d.brand)
        if d.kind:
            candidates.append(d.kind)
        if d.qty:
            candidates.append(d.qty)
        # Ajout d’un terme distinctif du titre si utile
        title_tokens = d.tokens()
        for t in [t for t in title_tokens if len(t) >= 3]:
            if len(candidates) >= self.max_keywords:
                break
            if t not in candidates and t not in {"lot", "promo", "pack"}:
                candidates.append(t)
        return candidates[: self.max_keywords]

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
    # Implémentation réelle à l’étape 2
    def search_by_ean(self, ean: str) -> Optional[ProductDescriptor]:
        raise NotImplementedError
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
    supports_keywords = False
    can_extract_ean_from_href = False
    def search_by_ean(self, ean: str) -> Optional[ProductDescriptor]:
        raise NotImplementedError
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
    supports_ean = False
    supports_keywords = True
    can_extract_ean_from_href = False
    _image_provider: Optional[ImageCompareProvider] = None
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
    supports_ean = False
    supports_keywords = True
    can_extract_ean_from_href = True  # cas particulier
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
    supports_ean = False
    supports_keywords = True
    can_extract_ean_from_href = False
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
            return None
        ean = self.extract_ean_from_info(info)
        if ean:
            pd.ean = ean
            if ean == src.ean:
                return 1.0
        return None

# Registres codés en dur. Ajouter un magasin = ajouter une classe + lister ici.
EAN_DIRECT_REGISTRY: List[type] = [
    CarrefourAdapter,
    AuchanAdapter,
    # CoursesUAdapter, ChronodriveAdapter, etc. à ajouter ici
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
    def __init__(self) -> None:
        self.consolidator = Consolidator()
        self.matcher = MatchingEngine(strict_qty=True)
        self.keywords: List[str] = []
        self.audit: List[AuditEntry] = []

    # Étape A: collecter depuis sites EAN-direct
    def collect_from_ean_sites(self, ean: str) -> ProductDescriptor:
        for cls in EAN_DIRECT_REGISTRY:
            adapter = cls()
            assert getattr(adapter, "supports_ean", False) is True
            try:
                pd = adapter.search_by_ean(ean)
                self.consolidator.add(pd)
            except NotImplementedError:
                # placeholder tant que l’implémentation n’est pas faite
                continue
        consolidated = self.consolidator.merged()
        if not consolidated.ean:
            consolidated.ean = ean
        return consolidated

    # Étape B: générer mots-clés
    def generate_keywords(self, consolidated: ProductDescriptor) -> List[str]:
        self.keywords = KeywordGenerator(max_keywords=4).make(consolidated)
        return self.keywords

    # Étape C: chercher sur sites sans EAN
    def search_on_keyword_sites(self, consolidated: ProductDescriptor) -> List[MatchResult]:
        results: List[MatchResult] = []
        orig_strict = self.matcher.strict_qty
        for cls in KEYWORD_REGISTRY:
            adapter = cls()
            assert getattr(adapter, "supports_keywords", False) is True
            try:
                override_strict = adapter.override_strict_qty()
                if override_strict is not None:
                    self.matcher.strict_qty = bool(override_strict)

                urls = adapter.search_by_keywords(self.keywords)
                for url in urls:
                    pd = adapter.parse_product_page(url)
                    if not pd:
                        continue
                    if getattr(adapter, "can_extract_ean_from_href", False):
                        m = re.search(r"\b(\d{8,14})\b", (url or ""))
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

                    forced = adapter.hard_validate(consolidated, url, pd)
                    if forced is not None:
                        score_forced = float(forced)
                        results.append(MatchResult(adapter=adapter.name, url=url, descriptor=pd, score=score_forced))
                        self.audit.append(
                            AuditEntry(
                                adapter=adapter.name,
                                url=url,
                                base_score=1.0,
                                threshold_used=0.0,
                                image_pass=False,
                                forced=score_forced,
                                reason="hard_validate",
                            )
                        )
                        continue

                    base_score = self.matcher.score(consolidated, pd)
                    score = base_score
                    img_pass = False
                    reason = "generic"
                    threshold_used = adapter.override_threshold() or 0.5

                    if adapter.name == "monoprix":
                        threshold_used = adapter.override_threshold() or 0.75
                        if score >= threshold_used:
                            img_pass = self.matcher.image_match(
                                consolidated.image_url,
                                pd.image_url,
                                provider=provider,
                            )
                            if img_pass:
                                score = max(score, 0.95)
                                reason = "mono_text+image"
                            else:
                                reason = "mono_text_only"
                        else:
                            reason = "mono_below_threshold"

                    include_candidate = score >= 0.5
                    if include_candidate:
                        results.append(MatchResult(adapter=adapter.name, url=url, descriptor=pd, score=score))
                        audit_reason = reason
                    else:
                        audit_reason = f"{reason}_filtered"

                    self.audit.append(
                        AuditEntry(
                            adapter=adapter.name,
                            url=url,
                            base_score=base_score,
                            threshold_used=threshold_used,
                            image_pass=img_pass,
                            forced=None,
                            reason=audit_reason,
                        )
                    )
            except NotImplementedError:
                continue
            finally:
                self.matcher.strict_qty = orig_strict
        # tri décroissant par score
        results.sort(key=lambda r: -r.score)
        return results

    # Étape D: décision
    def decide(self, consolidated: ProductDescriptor, candidates: List[MatchResult], threshold: float = 0.7
               ) -> Optional[MatchResult]:
        for c in candidates:
            adapter_cls = next((cls for cls in KEYWORD_REGISTRY if getattr(cls, "name", "") == c.adapter), None)
            thr = threshold
            if adapter_cls:
                adapter = adapter_cls()
                override_thr = adapter.override_threshold()
                if override_thr is not None:
                    thr = float(override_thr)
            if c.score >= 0.99 or self.matcher.is_match(consolidated, c.descriptor, threshold=thr):
                return c
        return None

# ---------- API haut niveau ----------
def find_equivalents(ean: str, threshold: float = 0.7) -> Tuple[ProductDescriptor, List[str], List[MatchResult], Optional[MatchResult]]:
    pipeline = FinderPipeline()
    consolidated = pipeline.collect_from_ean_sites(ean)
    keywords = pipeline.generate_keywords(consolidated)
    candidates = pipeline.search_on_keyword_sites(consolidated)
    decision = pipeline.decide(consolidated, candidates, threshold=threshold)
    return consolidated, keywords, candidates, decision

# ---------- Exécution de test manuelle ----------
if __name__ == "__main__":
    # Appel “dans le dur” pour tester la tuyauterie.
    EAN = "5411188118961"  # exemple
    consolidated, keywords, candidates, decision = find_equivalents(EAN)
    print("[Consolidated]", consolidated)
    print("[Keywords]", keywords)
    print("[Candidates top 5]", [(c.adapter, round(c.score, 3), c.url) for c in candidates[:5]])
    print("[Decision]", (decision.adapter, decision.url, round(decision.score, 3)) if decision else None)
