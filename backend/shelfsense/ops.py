"""Owner-side deterministic engine: dashboard summary, daily briefing and a keyword-routed copilot.

The Gemini-powered OpsCopilot (``agents/``) uses the *same* tools; this class is what answers when
no LLM credentials are configured or the model is unavailable, so the owner console never goes dark.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .textutil import normalize_tokens

if TYPE_CHECKING:
    from .context import AppContext


def inr(x: float) -> str:
    return f"₹{x:,.0f}"


class OpsEngine:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    def summary(self) -> dict:
        c = self.ctx
        s = c.demand.summary(days=7)
        reorders = c.restock.reorders()
        s["critical_reorders"] = sum(1 for r in reorders if r.priority == "critical")
        s["low_stock_skus"] = sum(1 for p in c.catalog.all_products() if p.stock <= 5)
        s["catalog_size"] = len(c.catalog.all_products())
        return s

    def briefing(self) -> dict:
        c = self.ctx
        plan = c.restock.plan()
        s = c.demand.summary(days=7)
        lines = []
        if s["queries"]:
            lines.append(
                f"{s['queries']} shopper requests in the last 7 days; {round((s['fulfilment_rate'] or 0) * 100)}% were fulfilled, "
                f"{s['unmet']} could not be served ({s['unmet_shoppers']} shoppers), about {inr(s['revenue_at_risk'])} of demand at risk."
            )
        if plan.opportunities:
            o = plan.opportunities[0]
            lines.append(
                f"Top opportunity: {o.action} ({o.confidence} confidence, ~{o.est_weekly_units:g} units/week)."
            )
        crit = [r for r in plan.reorders if r.priority == "critical"]
        if crit:
            lines.append(
                "Critical reorders: " + ", ".join(f"{r.name} (order {r.reorder_qty})" for r in crit[:4]) + "."
            )
        if s["waitlist_open"]:
            lines.append(
                f"{s['waitlist_open']} shoppers are waiting to be notified; fulfilling the top needs will message them automatically."
            )
        return {"headline": lines[0] if lines else "No activity yet.", "lines": lines, "summary": s}

    def answer(self, text: str) -> dict:
        """Keyword-routed answers over the same data the agents use."""
        c, t = self.ctx, text.lower()
        if re.search(r"restock|reorder|order|stock ?out|running out|low stock", t):
            recs = c.restock.reorders()[:6]
            if not recs:
                return {
                    "reply": "Nothing needs reordering right now — all SKUs cover their lead time plus review period.",
                    "data": [],
                }
            body = "\n".join(
                f"• {r.name}: order {r.reorder_qty} ({r.priority}) — {r.rationale}" for r in recs
            )
            return {
                "reply": f"Here is what to reorder, most urgent first:\n{body}",
                "data": [r.model_dump() for r in recs],
            }
        if re.search(r"unmet|demand|missing|asking|wanted|opportun|new product|list", t):
            ops = c.restock.opportunities()[:5]
            if not ops:
                return {
                    "reply": "No recurring unmet needs yet. Shoppers are finding what they ask for.",
                    "data": [],
                }
            body = "\n".join(f"• {o.action} [{o.confidence}; {o.unique_customers} shoppers]" for o in ops)
            return {"reply": f"Top unmet needs:\n{body}", "data": [o.model_dump() for o in ops]}
        if "forecast" in t or "predict" in t or "sell" in t:
            toks = set(normalize_tokens(re.sub(r"forecast|predict|sales|sell|next|week|days?", " ", t)))
            best = max(
                c.catalog.all_products(),
                key=lambda p: c.catalog.coverage(list(toks), p.sku) if toks else 0,
                default=None,
            )
            if best and toks and c.catalog.coverage(list(toks), best.sku) > 0.3:
                f = c.forecast.forecast(best, horizon=7)
                return {
                    "reply": f"{best.name}: expect ~{f.daily_mean:.1f} units/day (≈{sum(p.mean for p in f.forecast):.0f} over 7 days). "
                    f"Stock on hand: {best.stock}.",
                    "data": f.model_dump(),
                }
        if re.search(r"waitlist|waiting|notify", t):
            s = c.demand.summary()
            return {
                "reply": f"{s['waitlist_open']} shoppers are waiting; {s['waitlist_recovered']} have already been notified.",
                "data": s,
            }
        b = self.briefing()
        return {
            "reply": "\n".join(b["lines"])
            or "Ask me about restocking, unmet demand, forecasts or the waitlist.",
            "data": b["summary"],
        }
