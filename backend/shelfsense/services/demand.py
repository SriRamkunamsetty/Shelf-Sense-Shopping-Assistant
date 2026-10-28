"""Demand-signal service: capture every shopper need, cluster the unmet ones, quantify them.

This is the part existing retail tools lack: sales history only shows what *sold*; this shows what
shoppers *wanted but could not get* — and how fast that is growing.
"""

from __future__ import annotations

import hashlib
import logging
import statistics
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta

from ..domain import (
    AuditRecord,
    DemandEvent,
    NeedCluster,
    Outcome,
    SearchResult,
    WaitlistEntry,
    new_id,
    utcnow,
)
from ..store import Repo
from ..textutil import scrub_pii

log = logging.getLogger("shelfsense.demand")
JACCARD_MERGE = 0.6


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


class DemandService:
    def __init__(
        self,
        events: Repo[DemandEvent],
        waitlist: Repo[WaitlistEntry],
        audit: Repo[AuditRecord],
        clock: Callable[[], datetime] = utcnow,
        sink: Callable[[DemandEvent], None] | None = None,
    ) -> None:
        self.events = events
        self.waitlist = waitlist
        self.audit = audit
        self.clock = clock
        self.sink = sink  # optional analytics sink (BigQuery)

    # ---- capture -----------------------------------------------------------------------
    def log(
        self,
        *,
        customer_id: str,
        session_id: str,
        text: str,
        need_text: str,
        language: str,
        result: SearchResult,
        channel: str = "web",
        ts: datetime | None = None,
    ) -> DemandEvent:
        ev = DemandEvent(
            ts=ts or self.clock(),
            customer_id=customer_id,
            session_id=session_id,
            text=scrub_pii(text)[:300],
            need_text=scrub_pii(need_text)[:120] or scrub_pii(text)[:120],
            need_key=result.need_key,
            tokens=result.tokens,
            language=language,
            outcome=result.outcome,
            coverage=result.coverage,
            matched_skus=[m.sku for m in (result.exact or result.substitutes)][:3],
            budget=result.budget,
            est_value=round(result.est_value, 2),
            channel=channel,
        )
        self.events.put(ev)
        if self.sink:
            try:
                self.sink(ev)
            except Exception:  # analytics must never break the shopper experience
                log.warning("analytics sink failed for event %s", ev.id, exc_info=True)
        return ev

    def recent(self, days: int = 14, now: datetime | None = None) -> list[DemandEvent]:
        cutoff = (now or self.clock()) - timedelta(days=days)
        return sorted((e for e in self.events.list() if e.ts >= cutoff), key=lambda e: e.ts)

    # ---- analysis ----------------------------------------------------------------------
    def clusters(
        self, days: int = 14, now: datetime | None = None, include_fulfilled: bool = False
    ) -> list[NeedCluster]:
        now = now or self.clock()
        evs = [e for e in self.recent(days, now) if e.tokens and (include_fulfilled or e.outcome.is_unmet)]
        freq = Counter(e.need_key for e in evs)
        groups: list[dict] = []
        for key, _n in freq.most_common():  # most frequent phrasing becomes the cluster centroid
            toks = set(key.split())
            for g in groups:
                if _jaccard(toks, g["tokens"]) >= JACCARD_MERGE:
                    g["keys"].add(key)
                    break
            else:
                groups.append({"tokens": toks, "keys": {key}})

        waiting = [w for w in self.waitlist.list() if w.status == "waiting"]
        out: list[NeedCluster] = []
        for g in groups:
            ev = [e for e in evs if e.need_key in g["keys"]]
            if not ev:
                continue
            ev.sort(key=lambda e: e.ts)
            outcomes = Counter(e.outcome.value for e in ev)
            dominant = Outcome(outcomes.most_common(1)[0][0])
            uniq = {e.customer_id for e in ev}
            budgets = [e.budget for e in ev if e.budget]
            values = [e.est_value for e in ev if e.est_value > 0]
            unit = statistics.median(values) if values else 0.0
            w7 = now - timedelta(days=7)
            w14 = now - timedelta(days=14)
            last = sum(1 for e in ev if e.ts >= w7)
            prev = sum(1 for e in ev if w14 <= e.ts < w7)
            trend = (
                round((last - prev) / prev * 100, 1) if prev >= 3 else None
            )  # tiny baselines make % misleading
            label = Counter(e.need_text.lower() for e in ev).most_common(1)[0][0]
            skus = Counter(s for e in ev for s in e.matched_skus).most_common(3)
            wl = sum(1 for w in waiting if _jaccard(set(w.tokens), g["tokens"]) >= JACCARD_MERGE)
            cid = hashlib.sha1(" ".join(sorted(g["tokens"])).encode()).hexdigest()[:10]  # noqa: S324 - id only
            c = NeedCluster(
                cluster_id=cid,
                label=label,
                tokens=sorted(g["tokens"]),
                events=len(ev),
                unique_customers=len(uniq),
                outcomes=dict(outcomes),
                dominant_outcome=dominant,
                median_budget=statistics.median(budgets) if budgets else None,
                est_unit_value=round(unit, 2),
                revenue_at_risk=round(len(uniq) * unit, 2),
                first_seen=ev[0].ts,
                last_seen=ev[-1].ts,
                events_7d=last,
                events_prev_7d=prev,
                trend_pct=trend,
                languages=dict(Counter(e.language for e in ev)),
                waitlist_count=wl,
                sample_queries=list(dict.fromkeys(e.text for e in reversed(ev)))[:4],
                nearest_skus=[s for s, _ in skus],
            )
            c.priority = round(
                len(uniq) * 1.0 + c.events * 0.25 + (max(trend, 0) / 50 if trend else 0) + wl * 0.5, 2
            )
            out.append(c)
        out.sort(key=lambda c: c.priority, reverse=True)
        return out

    def summary(self, days: int = 7, now: datetime | None = None) -> dict:
        now = now or self.clock()
        evs = self.recent(days, now)
        total = len(evs)
        unmet = [e for e in evs if e.outcome.is_unmet]
        cl = self.clusters(days=days, now=now)
        waiting = [w for w in self.waitlist.list() if w.status == "waiting"]
        notified = [w for w in self.waitlist.list() if w.status == "notified"]
        return {
            "window_days": days,
            "queries": total,
            "fulfilled": total - len(unmet),
            "unmet": len(unmet),
            "fulfilment_rate": round((total - len(unmet)) / total, 3) if total else None,
            "unmet_shoppers": len({e.customer_id for e in unmet}),
            "open_needs": len(cl),
            "revenue_at_risk": round(sum(c.revenue_at_risk for c in cl), 2),
            "waitlist_open": len(waiting),
            "waitlist_recovered": len(notified),
            "outcome_mix": dict(Counter(e.outcome.value for e in evs)),
        }

    def unmet_for_sku(self, days: int = 7, now: datetime | None = None) -> dict[str, int]:
        """Unique shoppers per SKU who were turned away because it was out of stock."""
        by_sku: dict[str, set[str]] = {}
        for e in self.recent(days, now):
            if e.outcome is Outcome.OUT_OF_STOCK:
                for sku in e.matched_skus[:1]:
                    by_sku.setdefault(sku, set()).add(e.customer_id)
        return {k: len(v) for k, v in by_sku.items()}

    # ---- waitlist ----------------------------------------------------------------------
    def join_waitlist(
        self,
        *,
        customer_id: str,
        session_id: str,
        need_text: str,
        tokens: list[str],
        key: str,
        budget: float | None,
        language: str,
        audit: bool = True,
    ) -> WaitlistEntry:
        for w in self.waitlist.list({"customer_id": customer_id, "need_key": key}):
            if w.status == "waiting":  # idempotent, but keep the entry current with the latest conversation
                w.language, w.budget = language, budget if budget is not None else w.budget
                w.consent_at = w.consent_at or self.clock()
                self.waitlist.put(w)
                return w
        entry = WaitlistEntry(
            customer_id=customer_id,
            need_key=key,
            need_text=need_text,
            tokens=tokens,
            budget=budget,
            language=language,
            session_id=session_id,
            consent_at=self.clock(),
        )
        self.waitlist.put(entry)
        if audit:
            self.audit.put(
                AuditRecord(
                    id=new_id("au_"),
                    ts=self.clock(),
                    actor=f"shopper:{customer_id}",
                    action="waitlist.join",
                    details={"need": need_text, "consent": True},
                )
            )
        return entry
