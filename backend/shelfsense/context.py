"""Application container: wires stores, services, engines and (optionally) the ADK runtime."""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime, timedelta

from .analytics import build_sink
from .config import Settings, export_genai_env
from .domain import (
    AuditRecord,
    Customer,
    DemandEvent,
    Notification,
    Product,
    PurchaseOrder,
    WaitlistEntry,
)
from .ops import OpsEngine
from .seed import SCRIPTED_HISTORY, build_customers, build_products, build_sales
from .services.catalog import CatalogService
from .services.demand import DemandService
from .services.forecast import ForecastService, MemorySales
from .services.inventory import InventoryService, RestockService
from .services.outreach import InAppChannel, OutreachService, WebhookChannel
from .shopper import SessionState, ShopperEngine
from .store import Repo, build_store

log = logging.getLogger("shelfsense.context")

_CTX: AppContext | None = None


class AppContext:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        export_genai_env(settings)
        self.store = build_store(
            settings.store_backend, settings.google_cloud_project, settings.firestore_database
        )
        s = self.store
        self.products = Repo(s, "products", Product, "sku")
        self.customers = Repo(s, "customers", Customer)
        self.events = Repo(s, "events", DemandEvent)
        self.waitlist = Repo(s, "waitlist", WaitlistEntry)
        self.notifications = Repo(s, "notifications", Notification)
        self.pos = Repo(s, "purchase_orders", PurchaseOrder)
        self.audit = Repo(s, "audit", AuditRecord)
        self.sessions = Repo(s, "sessions", SessionState)

        self.catalog = CatalogService(self.products, settings)
        self.demand = DemandService(self.events, self.waitlist, self.audit, sink=build_sink(settings))
        if settings.sales_backend == "bigquery":
            from .services.sales_bq import BigQuerySales

            if not settings.bigquery_dataset:
                raise ValueError("SALES_BACKEND=bigquery requires BIGQUERY_DATASET")
            self.sales = BigQuerySales(settings.google_cloud_project, settings.bigquery_dataset)
        else:
            self.sales = MemorySales({})
        self.forecast = ForecastService(
            self.sales, settings.capture_rate, unmet_lookup=self.demand.unmet_for_sku
        )
        channels = [InAppChannel()]
        if settings.notify_webhook_url:
            channels.append(WebhookChannel(settings.notify_webhook_url))
        self.outreach = OutreachService(
            self.catalog,
            self.waitlist,
            self.customers,
            self.notifications,
            channels,
            full_coverage=settings.full_match_coverage,
        )
        self.restock = RestockService(self.catalog, self.forecast, self.demand, settings)
        self.inventory = InventoryService(self.catalog, self.products, self.pos, self.audit, self.outreach)
        self.shopper = ShopperEngine(self.catalog, self.demand, self.customers, self.sessions)
        self.ops = OpsEngine(self)
        self.runtime = None  # set by attach_runtime()

    # ---- demo data -----------------------------------------------------------------------
    def reset_demo(self, seed: int = 11) -> None:
        for coll in (
            "products",
            "customers",
            "events",
            "waitlist",
            "notifications",
            "purchase_orders",
            "audit",
            "sessions",
        ):
            self.store.clear(coll)
        self.forecast._cache.clear()
        self.seed_demo(seed)

    def seed_demo(self, seed: int = 11) -> None:
        rng = random.Random(seed)
        now = datetime.now(UTC)
        for p in build_products():
            self.products.put(p)
        self.catalog.reindex()
        for c in build_customers(rng):
            self.customers.put(c)
        if isinstance(self.sales, MemorySales):
            self.sales._data = build_sales(now.date())
        customers = self.customers.list()
        for query, lang, count, recent_share in SCRIPTED_HISTORY:
            for _ in range(count):
                cust = rng.choice(customers)
                age_days = rng.uniform(0, 7) if rng.random() < recent_share else rng.uniform(7, 14)
                ts = now - timedelta(days=age_days, hours=rng.uniform(0, 6))
                sid = f"seed-{rng.randrange(10**6)}"
                res, ev = self.shopper.search_and_log(
                    customer_id=cust.id,
                    session_id=sid,
                    text=query,
                    need_text=None,
                    language=lang,
                    channel=cust.channel,
                    ts=ts,
                )
                if res.outcome.is_unmet and cust.consent_notify and rng.random() < 0.5:
                    self.demand.join_waitlist(
                        customer_id=cust.id,
                        session_id=sid,
                        need_text=ev.need_text,
                        tokens=res.tokens,
                        key=res.need_key,
                        budget=res.budget,
                        language=cust.language,
                        audit=False,
                    )
        log.info(
            "seeded demo data: %d products, %d events", len(self.products.list()), len(self.events.list())
        )


def build_context(settings: Settings, seed: bool | None = None) -> AppContext:
    ctx = AppContext(settings)
    do_seed = settings.seed_on_start if seed is None else seed
    if do_seed and not ctx.products.list():
        ctx.seed_demo()
    elif do_seed and isinstance(ctx.sales, MemorySales) and not ctx.sales._data:
        ctx.sales._data = (
            build_sales()
        )  # persistent store already has products; regenerate demo sales history
    if settings.llm_enabled:
        from .agents.runtime import AgentRuntime

        ctx.runtime = AgentRuntime(ctx)
    set_context(ctx)
    return ctx


def set_context(ctx: AppContext) -> None:
    global _CTX
    _CTX = ctx


def get_context() -> AppContext:
    if _CTX is None:
        raise RuntimeError("AppContext not initialised")
    return _CTX
