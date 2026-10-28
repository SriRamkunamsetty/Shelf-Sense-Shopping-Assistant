"""Inventory intelligence: reorder recommendations, new-listing opportunities, and the human-approved
actions (purchase orders, receiving stock, listing a new product) that close the loop."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timedelta

from ..config import Settings
from ..domain import (
    AuditRecord,
    NeedCluster,
    Notification,
    Opportunity,
    Outcome,
    Product,
    PurchaseOrder,
    ReorderRec,
    RestockPlan,
    utcnow,
)
from ..store import Repo
from .catalog import CatalogService
from .demand import DemandService
from .forecast import ForecastService
from .outreach import OutreachService


def _round_up(qty: float, pack: int) -> int:
    pack = max(pack, 1)
    return int(math.ceil(max(qty, 0) / pack) * pack)


class RestockService:
    def __init__(
        self, catalog: CatalogService, forecast: ForecastService, demand: DemandService, settings: Settings
    ) -> None:
        self.catalog, self.forecast, self.demand, self.s = catalog, forecast, demand, settings

    # ---- reorders for existing SKUs ------------------------------------------------------
    def reorders(self) -> list[ReorderRec]:
        recs: list[ReorderRec] = []
        turned_away = self.demand.unmet_for_sku()
        for p in self.catalog.all_products():
            cover = p.lead_time_days + self.s.review_period_days
            fc = self.forecast.forecast(p, horizon=max(cover, 7))
            mu = sum(pt.mean for pt in fc.forecast[:cover]) / cover
            if mu <= 0.05:
                continue
            safety = math.ceil(self.s.service_level_z * fc.daily_sigma * math.sqrt(cover))
            position = p.stock + p.on_order
            expected = mu * cover
            if position >= expected:  # already covered through lead time + review period
                continue
            qty = _round_up(expected + safety - position, p.pack_size)
            days_cover = round(p.stock / mu, 1)
            priority = (
                "critical"
                if p.stock == 0 or days_cover < p.lead_time_days
                else ("high" if days_cover < cover else "normal")
            )
            why = f"Selling ~{mu:.1f}/day; {p.stock} on hand covers {days_cover} days vs a {p.lead_time_days}-day lead time."
            if p.on_order:
                why += f" {p.on_order} already on order."
            if fc.lost_units_estimate >= 5:
                why += f" Past stock-outs hid ~{fc.lost_units_estimate:.0f} units of demand (corrected in the forecast)."
            if turned_away.get(p.sku):
                why += f" {turned_away[p.sku]} shopper(s) were turned away this week (+{fc.signal_uplift_per_day:.1f}/day added)."
            recs.append(
                ReorderRec(
                    sku=p.sku,
                    name=p.name,
                    stock=p.stock,
                    on_order=p.on_order,
                    lead_time_days=p.lead_time_days,
                    days_of_cover=days_cover,
                    forecast_next_7d=round(sum(pt.mean for pt in fc.forecast[:7]), 1),
                    safety_stock=safety,
                    reorder_qty=qty,
                    unit_cost=p.cost,
                    order_cost=round(qty * p.cost, 2),
                    revenue_protected=round(min(qty, expected) * p.price, 2),
                    priority=priority,
                    rationale=why,
                )
            )
        order = {"critical": 0, "high": 1, "normal": 2}
        recs.sort(key=lambda r: (order[r.priority], -r.revenue_protected))
        return recs

    # ---- opportunities from unmet demand --------------------------------------------------
    def opportunities(self, days: int = 14, reorders: list[ReorderRec] | None = None) -> list[Opportunity]:
        reorders = reorders if reorders is not None else self.reorders()
        by_sku = {r.sku: r for r in reorders}
        out: list[Opportunity] = []
        for c in self.demand.clusters(days=days):
            if c.unique_customers < 2:
                continue  # one-off requests are noise, not signal
            out.append(self._opportunity(c, days, by_sku))
        order = {"high": 0, "medium": 1, "low": 2}
        out.sort(key=lambda o: (order[o.confidence], -o.revenue_at_risk))
        return out

    def _opportunity(self, c: NeedCluster, days: int, reorders: dict[str, ReorderRec]) -> Opportunity:
        conf = "high" if c.unique_customers >= 8 else "medium" if c.unique_customers >= 4 else "low"
        reach = max(self.s.assistant_reach, 0.05)
        weekly = round(max(c.unique_customers * 7 / days * self.s.capture_rate / reach, 0.5), 1)
        price = c.median_budget or c.est_unit_value
        price = float(5 * round(price / 5)) if price else 0.0
        base = dict(  # noqa: C408
            cluster_id=c.cluster_id,
            label=c.label,
            unique_customers=c.unique_customers,
            events=c.events,
            trend_pct=c.trend_pct,
            confidence=conf,
            est_weekly_units=weekly,
            suggested_name=c.label.title(),
            suggested_price=price,
            revenue_at_risk=c.revenue_at_risk,
            nearest_skus=c.nearest_skus,
            waitlist_count=c.waitlist_count,
        )
        assumption = f"assuming the assistant sees ~{int(reach * 100)}% of shoppers and {int(self.s.capture_rate * 100)}% would buy"
        if c.dominant_outcome is Outcome.OUT_OF_STOCK and c.nearest_skus:
            sku = c.nearest_skus[0]
            prod = self.catalog.get(sku)
            r = reorders.get(sku)
            qty = r.reorder_qty if r else _round_up(weekly * 2, prod.pack_size if prod else 1)
            return Opportunity(
                **base
                | {
                    "suggested_name": prod.name if prod else c.label.title(),
                    "suggested_price": prod.price if prod else price,
                },
                kind="restock",
                suggested_qty=qty,
                linked_sku=sku,
                action=f"Restock {prod.name if prod else sku}: {c.unique_customers} shoppers asked while it was out of stock.",
                rationale=f"{c.events} requests in {days} days hit an empty shelf"
                + (f"; reorder plan already proposes {qty} units." if r else "."),
            )
        if c.dominant_outcome is Outcome.OVER_BUDGET:
            ref = self.catalog.get(c.nearest_skus[0]) if c.nearest_skus else None
            gap = round((ref.price - (c.median_budget or 0)), 0) if ref and c.median_budget else None
            return Opportunity(
                **base | {"suggested_price": c.median_budget or price},
                kind="price_gap",
                suggested_qty=0,
                linked_sku=ref.sku if ref else None,
                action=(
                    f"Price gap: shoppers want ≤ ₹{c.median_budget:.0f} but {ref.name} is ₹{ref.price:.0f}"
                    f" (gap ₹{gap:.0f}). Source a cheaper variant or run a promotion."
                )
                if ref and c.median_budget
                else "Price gap: shoppers' budgets sit below current prices.",
                rationale=f"{c.unique_customers} shoppers left because of price, not availability.",
            )
        qty = max(6, _round_up(weekly * 3, 6))
        return Opportunity(
            **base,
            kind="new_listing",
            suggested_qty=qty,
            linked_sku=None,
            action=f"Pilot-list “{c.label.title()}”: {c.unique_customers} shoppers asked, nothing close in stock.",
            rationale=f"Estimated {weekly} units/week ({assumption}); start with {qty} units (~3 weeks) and re-check.",
        )

    def plan(self, days: int = 14) -> RestockPlan:
        reorders = self.reorders()
        opps = self.opportunities(days=days, reorders=reorders)
        return RestockPlan(
            generated_at=utcnow(),
            reorders=reorders,
            opportunities=opps,
            total_order_cost=round(sum(r.order_cost for r in reorders), 2),
            total_revenue_at_risk=round(sum(o.revenue_at_risk for o in opps), 2),
        )


class InventoryService:
    """Write-side actions. Every one is triggered by a human click / explicit API call and audited."""

    def __init__(
        self,
        catalog: CatalogService,
        products: Repo[Product],
        pos: Repo[PurchaseOrder],
        audit: Repo[AuditRecord],
        outreach: OutreachService,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.catalog, self.products, self.pos, self.audit, self.outreach, self.clock = (
            catalog,
            products,
            pos,
            audit,
            outreach,
            clock,
        )

    def _audit(self, actor: str, action: str, **details) -> None:
        self.audit.put(AuditRecord(ts=self.clock(), actor=actor, action=action, details=details))

    def approve_po(self, sku: str, qty: int, actor: str = "owner", note: str = "") -> PurchaseOrder:
        p = self.catalog.get(sku)
        if p is None:
            raise KeyError(sku)
        if qty <= 0 or qty > 100_000:
            raise ValueError("qty must be between 1 and 100000")
        po = PurchaseOrder(
            sku=sku,
            qty=qty,
            unit_cost=p.cost,
            created_at=self.clock(),
            approved_by=actor,
            note=note,
            expected_at=self.clock() + timedelta(days=p.lead_time_days),
        )
        self.pos.put(po)
        p.on_order += qty
        self.products.put(p)
        self.catalog.reindex()
        self._audit(actor, "po.approve", sku=sku, qty=qty, po=po.id)
        return po

    def receive_po(self, po_id: str, actor: str = "owner") -> tuple[PurchaseOrder, list[Notification]]:
        po = self.pos.get(po_id)
        if po is None:
            raise KeyError(po_id)
        if po.status != "approved":
            raise ValueError(f"purchase order is {po.status}")
        p = self.catalog.get(po.sku)
        if p is None:
            raise KeyError(po.sku)
        p.stock += po.qty
        p.on_order = max(0, p.on_order - po.qty)
        self.products.put(p)
        po.status, po.received_at = "received", self.clock()
        self.pos.put(po)
        self.catalog.reindex()
        notes = self.outreach.notify_for_product(self.catalog.get(p.sku) or p)
        self._audit(actor, "po.receive", sku=p.sku, qty=po.qty, notified=len(notes))
        return po, notes

    def list_new_product(
        self,
        *,
        name: str,
        price: float,
        qty: int,
        category: str = "Grocery",
        cost: float | None = None,
        tags: list[str] | None = None,
        aliases: list[str] | None = None,
        actor: str = "owner",
    ) -> tuple[Product, list[Notification]]:
        if not name.strip() or price <= 0 or qty <= 0:
            raise ValueError("name, price and qty are required")
        sku = (
            "NEW-"
            + "".join(ch for ch in name.upper() if ch.isalnum())[:10]
            + f"-{len(self.catalog.all_products()) + 1}"
        )
        prod = Product(
            sku=sku,
            name=name.strip(),
            category=category,
            price=price,
            cost=cost if cost is not None else round(price * 0.75, 2),
            stock=qty,
            lead_time_days=5,
            pack_size=6,
            tags=tags or [],
            aliases=aliases or [],
            created_at=self.clock(),
        )
        self.products.put(prod)
        self.catalog.reindex()
        notes = self.outreach.notify_for_product(prod)
        self._audit(actor, "product.list", sku=sku, qty=qty, price=price, notified=len(notes))
        return prod, notes

    def receive_stock(self, sku: str, qty: int, actor: str = "owner") -> tuple[Product, list[Notification]]:
        p = self.catalog.get(sku)
        if p is None:
            raise KeyError(sku)
        if qty <= 0:
            raise ValueError("qty must be positive")
        p.stock += qty
        self.products.put(p)
        self.catalog.reindex()
        notes = self.outreach.notify_for_product(p)
        self._audit(actor, "stock.receive", sku=sku, qty=qty, notified=len(notes))
        return p, notes
