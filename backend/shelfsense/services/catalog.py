"""Catalogue search with *need coverage* scoring.

Instead of returning "top-k similar items" (which always returns *something*), we measure how
much of the shopper's stated need each product actually covers, using IDF-weighted token
coverage. That single number lets us tell apart five very different situations — in stock,
out of stock, over budget, only a substitute exists, and not carried at all — which is the raw
material for demand intelligence.

For very large catalogues, swap this class for Vertex AI Search for commerce behind the same
``search`` signature; the rest of the system only consumes ``SearchResult``.
"""

from __future__ import annotations

import math
import statistics
import threading

from ..config import Settings
from ..domain import Match, Outcome, Product, SearchResult
from ..store import Repo
from ..textutil import need_key, normalize_tokens, parse_budget

# field weights: how strongly a match in that field says "this product *is* the thing"
W_NAME, W_TAG, W_BRAND, W_CAT, W_ATTR = 1.0, 1.0, 0.85, 0.7, 0.7


class CatalogService:
    def __init__(self, products: Repo[Product], settings: Settings) -> None:
        self.repo = products
        self.s = settings
        self._lock = threading.RLock()
        self._docs: dict[str, dict[str, float]] = {}  # sku -> {token: weight}
        self._df: dict[str, int] = {}
        self._by_sku: dict[str, Product] = {}
        self.reindex()

    # ---- index -------------------------------------------------------------------------
    @staticmethod
    def _doc_tokens(p: Product) -> dict[str, float]:
        weights: dict[str, float] = {}

        def add(text: str, w: float) -> None:
            for t in normalize_tokens(text):
                weights[t] = max(weights.get(t, 0.0), w)

        add(p.name, W_NAME)
        for t in p.tags:
            add(t, W_TAG)
        for a in p.aliases:
            add(a, W_TAG)
        add(p.brand, W_BRAND)
        add(p.category, W_CAT)
        for v in p.attributes.values():
            add(v, W_ATTR)
        return weights

    def reindex(self) -> None:
        with self._lock:
            prods = [p for p in self.repo.list() if p.active]
            self._by_sku = {p.sku: p for p in prods}
            self._docs = {p.sku: self._doc_tokens(p) for p in prods}
            df: dict[str, int] = {}
            for toks in self._docs.values():
                for t in toks:
                    df[t] = df.get(t, 0) + 1
            self._df = df

    def idf(self, token: str) -> float:
        n = max(len(self._docs), 1)
        df = self._df.get(token, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    # ---- accessors ---------------------------------------------------------------------
    def all_products(self) -> list[Product]:
        with self._lock:
            return list(self._by_sku.values())

    def get(self, sku: str) -> Product | None:
        return self._by_sku.get(sku)

    def median_price(self) -> float:
        prices = [p.price for p in self._by_sku.values()]
        return statistics.median(prices) if prices else 0.0

    # ---- scoring -----------------------------------------------------------------------
    def coverage(self, tokens: list[str], sku: str) -> float:
        """IDF-weighted share of the query that this product covers (0..1)."""
        doc = self._docs.get(sku)
        if not doc or not tokens:
            return 0.0
        total = sum(self.idf(t) for t in tokens)
        if total <= 0:
            return 0.0
        got = sum(self.idf(t) * doc[t] for t in tokens if t in doc)
        return round(got / total, 4)

    def _match(self, p: Product, cov: float) -> Match:
        return Match(
            sku=p.sku,
            name=p.name,
            price=p.price,
            stock=p.stock,
            category=p.category,
            coverage=cov,
            in_stock=p.stock > 0,
        )

    # ---- search ------------------------------------------------------------------------
    def search(self, query: str, max_price: float | None = None, limit: int = 4) -> SearchResult:
        budget, stripped = parse_budget(query)
        if max_price is not None:
            budget = max_price
        tokens = normalize_tokens(stripped)
        key = need_key(tokens)
        with self._lock:
            scored = [(self.coverage(tokens, sku), p) for sku, p in self._by_sku.items()]
        scored = [(c, p) for c, p in scored if c > 0]
        scored.sort(key=lambda cp: (-cp[0], -(cp[1].stock > 0), cp[1].price))

        full, part = self.s.full_match_coverage, self.s.partial_match_coverage
        exact = [(c, p) for c, p in scored if c >= full]
        partial = [(c, p) for c, p in scored if part <= c < full]
        best = scored[0][0] if scored else 0.0

        def within(p: Product) -> bool:
            return budget is None or p.price <= budget

        if not tokens:
            return SearchResult(
                query=query,
                tokens=[],
                budget=budget,
                outcome=Outcome.NOT_CARRIED,
                coverage=0.0,
                need_key="",
                est_value=budget or self.median_price(),
            )

        if exact:
            ok = [(c, p) for c, p in exact if within(p)]
            if not ok:
                cheapest = min(exact, key=lambda cp: cp[1].price)
                return SearchResult(
                    query=query,
                    tokens=tokens,
                    budget=budget,
                    outcome=Outcome.OVER_BUDGET,
                    coverage=best,
                    exact=[self._match(p, c) for c, p in sorted(exact, key=lambda cp: cp[1].price)[:limit]],
                    need_key=key,
                    est_value=cheapest[1].price,
                )
            stocked = [(c, p) for c, p in ok if p.stock > 0]
            if stocked:
                return SearchResult(
                    query=query,
                    tokens=tokens,
                    budget=budget,
                    outcome=Outcome.IN_STOCK,
                    coverage=best,
                    exact=[self._match(p, c) for c, p in stocked[:limit]],
                    need_key=key,
                    est_value=stocked[0][1].price,
                )
            subs = [(c, p) for c, p in partial if p.stock > 0 and within(p)]
            return SearchResult(
                query=query,
                tokens=tokens,
                budget=budget,
                outcome=Outcome.OUT_OF_STOCK,
                coverage=best,
                exact=[self._match(p, c) for c, p in ok[:limit]],
                substitutes=[self._match(p, c) for c, p in subs[:limit]],
                need_key=key,
                est_value=ok[0][1].price,
            )

        if partial:
            subs = [(c, p) for c, p in partial if p.stock > 0 and within(p)] or [
                (c, p) for c, p in partial if p.stock > 0
            ]
            est = budget or statistics.median([p.price for _c, p in partial])
            return SearchResult(
                query=query,
                tokens=tokens,
                budget=budget,
                outcome=Outcome.PARTIAL,
                coverage=best,
                substitutes=[self._match(p, c) for c, p in subs[:limit]],
                need_key=key,
                est_value=float(est),
            )

        return SearchResult(
            query=query,
            tokens=tokens,
            budget=budget,
            outcome=Outcome.NOT_CARRIED,
            coverage=best,
            need_key=key,
            est_value=float(budget or self.median_price()),
        )
