"""HTTP API (FastAPI). Run with: uvicorn shelfsense.api.main:app"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..config import Settings, get_settings
from ..context import AppContext, build_context
from ..textutil import sanitize_user_text
from .support import RateLimiter, client_key, make_ops_guard, request_id_var, setup_logging

log = logging.getLogger("shelfsense.api")

ID_PATTERN = r"^[A-Za-z0-9_\-]{1,48}$"


# ---- request models -------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=600)
    customer_id: str = Field(default="guest", pattern=ID_PATTERN)
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16], pattern=ID_PATTERN)
    language: Literal["en", "hi", "te", "auto"] | None = "auto"
    channel: Literal["web", "voice", "whatsapp"] = "web"


class OpsChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=600)
    session_id: str = Field(default="ops", pattern=ID_PATTERN)


class PORequest(BaseModel):
    sku: str
    qty: int = Field(gt=0, le=100_000)
    note: str = Field(default="", max_length=200)


class ReceiveRequest(BaseModel):
    sku: str
    qty: int = Field(gt=0, le=100_000)


class ListingRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    price: float = Field(gt=0, le=1_000_000)
    qty: int = Field(gt=0, le=100_000)
    category: str = Field(default="Grocery", max_length=40)
    aliases: list[str] = Field(default_factory=list, max_length=10)
    tags: list[str] = Field(default_factory=list, max_length=10)


class SimulateRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    count: int = Field(default=5, ge=1, le=50)
    language: Literal["en", "hi", "te"] = "en"
    join_waitlist: bool = True


def create_app(settings: Settings | None = None, ctx: AppContext | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level, json_logs=settings.app_env != "local")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.ctx = ctx or build_context(settings)
        log.info(
            "ShelfSense %s started (env=%s, llm=%s, store=%s)",
            __version__,
            settings.app_env,
            "gemini" if app.state.ctx.runtime else "offline",
            settings.store_backend,
        )
        yield

    app = FastAPI(
        title="ShelfSense API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-API-Key"],
        max_age=600,
    )
    limiter = RateLimiter(settings.chat_rate_limit_per_min)
    ops_guard = make_ops_guard(settings.ops_api_key)

    def C(request: Request) -> AppContext:  # noqa: N802 - short dependency alias
        return request.app.state.ctx

    @app.middleware("http")
    async def observability(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request_id_var.set(rid)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error on %s %s", request.method, request.url.path)
            response = JSONResponse({"detail": "internal error", "request_id": rid}, status_code=500)
        response.headers["x-request-id"] = rid
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("referrer-policy", "no-referrer")
        response.headers.setdefault("permissions-policy", "microphone=(self)")
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            log.info(
                "%s %s -> %s in %.0fms",
                request.method,
                request.url.path,
                response.status_code,
                (time.perf_counter() - t0) * 1000,
            )
        return response

    # ---- health ----------------------------------------------------------------------------
    @app.get("/api/health")
    def health(request: Request):
        c = C(request)
        return {
            "status": "ok",
            "version": __version__,
            "engine": "gemini" if c.runtime else "offline",
            "model": settings.gemini_model if c.runtime else None,
            "store": settings.store_backend,
            "products": len(c.catalog.all_products()),
            "demo_mode": settings.demo_mode,
        }

    # ---- shopper-facing --------------------------------------------------------------------
    @app.post("/api/chat")
    async def chat(req: ChatRequest, request: Request):
        if not limiter.check(client_key(request)):
            raise HTTPException(429, "Too many requests — please slow down.")
        c = C(request)
        text = sanitize_user_text(req.message)
        if not text:
            raise HTTPException(422, "empty message")
        hint = None if req.language in (None, "auto") else req.language
        if c.runtime is not None:
            from ..textutil import detect_language

            lang = hint or detect_language(text)
            try:
                return await asyncio.wait_for(
                    c.runtime.shopper_turn(
                        customer_id=req.customer_id,
                        session_id=req.session_id,
                        text=text,
                        language=lang,
                        channel=req.channel,
                    ),
                    timeout=settings.llm_timeout_s,
                )
            except Exception:  # degrade gracefully: the shopper must always get an answer
                log.exception("Gemini path failed; falling back to deterministic engine")
                reply = await asyncio.to_thread(
                    c.shopper.reply,
                    customer_id=req.customer_id,
                    session_id=req.session_id,
                    text=text,
                    language_hint=hint,
                    channel=req.channel,
                )
                reply.engine = "offline-fallback"
                return reply
        return await asyncio.to_thread(
            c.shopper.reply,
            customer_id=req.customer_id,
            session_id=req.session_id,
            text=text,
            language_hint=hint,
            channel=req.channel,
        )

    @app.get("/api/catalog")
    def catalog(request: Request, q: str = "", limit: int = 40):
        c = C(request)
        if q:
            res = c.catalog.search(sanitize_user_text(q, 100), limit=min(limit, 20))
            return {"outcome": res.outcome, "items": [*res.exact, *res.substitutes]}
        items = sorted(c.catalog.all_products(), key=lambda p: (p.category, p.name))[: min(limit, 100)]
        return {
            "items": [
                {"sku": p.sku, "name": p.name, "price": p.price, "stock": p.stock, "category": p.category}
                for p in items
            ]
        }

    @app.get("/api/customers/{customer_id}/notifications")
    def inbox(customer_id: str, request: Request):
        if not _valid_id(customer_id):
            raise HTTPException(422, "bad id")
        return {"notifications": C(request).outreach.inbox(customer_id)}

    @app.post("/api/customers/{customer_id}/notifications/read")
    def inbox_read(customer_id: str, request: Request):
        if not _valid_id(customer_id):
            raise HTTPException(422, "bad id")
        C(request).outreach.mark_read(customer_id)
        return {"ok": True}

    # ---- owner console (protected when OPS_API_KEY is set) --------------------------------
    owner = [Depends(ops_guard)]

    @app.get("/api/insights/summary", dependencies=owner)
    def insights_summary(request: Request):
        return C(request).ops.summary()

    @app.get("/api/insights/unmet", dependencies=owner)
    def insights_unmet(request: Request, days: int = 14):
        cl = C(request).demand.clusters(days=max(1, min(days, 60)))
        return {"days": days, "clusters": cl}

    @app.get("/api/insights/briefing", dependencies=owner)
    def briefing(request: Request):
        return C(request).ops.briefing()

    @app.get("/api/forecast/evaluation", dependencies=owner)
    def forecast_eval(request: Request):
        c = C(request)
        return c.forecast.fleet_backtest([p.sku for p in c.catalog.all_products()])

    @app.get("/api/forecast/{sku}", dependencies=owner)
    def forecast(sku: str, request: Request, horizon: int = 14, backtest: bool = True):
        c = C(request)
        p = c.catalog.get(sku)
        if p is None:
            raise HTTPException(404, "unknown sku")
        return c.forecast.forecast(p, horizon=max(1, min(horizon, 28)), with_backtest=backtest)

    @app.get("/api/restock/plan", dependencies=owner)
    def restock_plan(request: Request):
        return C(request).restock.plan()

    @app.get("/api/inventory", dependencies=owner)
    def inventory(request: Request):
        return {"items": sorted(C(request).catalog.all_products(), key=lambda p: (p.stock, p.name))}

    @app.post("/api/purchase-orders", dependencies=owner)
    def create_po(body: PORequest, request: Request):
        try:
            return C(request).inventory.approve_po(body.sku, body.qty, note=body.note)
        except KeyError as exc:
            raise HTTPException(404, "unknown sku") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/purchase-orders", dependencies=owner)
    def list_pos(request: Request):
        return {"purchase_orders": sorted(C(request).pos.list(), key=lambda p: p.created_at, reverse=True)}

    @app.post("/api/purchase-orders/{po_id}/receive", dependencies=owner)
    def receive_po(po_id: str, request: Request):
        try:
            po, notes = C(request).inventory.receive_po(po_id)
        except KeyError as exc:
            raise HTTPException(404, "unknown purchase order") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"purchase_order": po, "notifications": notes}

    @app.post("/api/inventory/receive", dependencies=owner)
    def receive_stock(body: ReceiveRequest, request: Request):
        try:
            p, notes = C(request).inventory.receive_stock(body.sku, body.qty)
        except KeyError as exc:
            raise HTTPException(404, "unknown sku") from exc
        return {"product": p, "notifications": notes}

    @app.post("/api/listings", dependencies=owner)
    def new_listing(body: ListingRequest, request: Request):
        try:
            p, notes = C(request).inventory.list_new_product(
                name=body.name,
                price=body.price,
                qty=body.qty,
                category=body.category,
                aliases=body.aliases,
                tags=body.tags,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"product": p, "notifications": notes}

    @app.get("/api/waitlist", dependencies=owner)
    def waitlist(request: Request):
        c = C(request)
        items = sorted(c.waitlist.list(), key=lambda w: w.created_at, reverse=True)[:100]
        return {
            "waitlist": items,
            "notifications": sorted(c.notifications.list(), key=lambda n: n.created_at, reverse=True)[:50],
        }

    @app.get("/api/audit", dependencies=owner)
    def audit(request: Request, limit: int = 50):
        return {"audit": sorted(C(request).audit.list(), key=lambda a: a.ts, reverse=True)[: min(limit, 200)]}

    @app.post("/api/ops/chat", dependencies=owner)
    async def ops_chat(req: OpsChatRequest, request: Request):
        c = C(request)
        text = sanitize_user_text(req.message)
        if c.runtime is not None:
            try:
                reply, trace = await asyncio.wait_for(
                    c.runtime.ops_turn(session_id=req.session_id, text=text),
                    timeout=settings.llm_timeout_s * 2,
                )
                return {"reply": reply, "engine": "gemini", "trace": trace}
            except Exception:
                log.exception("ops copilot Gemini path failed; using deterministic engine")
        out = await asyncio.to_thread(c.ops.answer, text)
        return {"reply": out["reply"], "engine": "offline", "trace": [], "data": out.get("data")}

    # ---- demo helpers (disabled when DEMO_MODE=false) ---------------------------------------
    if settings.demo_mode:

        @app.get("/api/demo/customers", dependencies=owner)
        def demo_customers(request: Request):
            return {"customers": [c for c in C(request).customers.list() if c.id.startswith("c")][:12]}

        @app.post("/api/demo/simulate", dependencies=owner)
        def demo_simulate(body: SimulateRequest, request: Request):
            """Push N synthetic shoppers through the real search → signal → waitlist pipeline."""
            c = C(request)
            rng = random.Random()
            pool = c.customers.list()
            outcomes: dict[str, int] = {}
            for _ in range(body.count):
                cust = rng.choice(pool)
                sid = f"sim-{uuid.uuid4().hex[:8]}"
                res, ev = c.shopper.search_and_log(
                    customer_id=cust.id,
                    session_id=sid,
                    text=body.query,
                    need_text=None,
                    language=body.language,
                    channel=cust.channel,
                    ts=datetime.now(UTC),
                )
                outcomes[res.outcome.value] = outcomes.get(res.outcome.value, 0) + 1
                if body.join_waitlist and res.outcome.is_unmet and res.tokens:
                    c.demand.join_waitlist(
                        customer_id=cust.id,
                        session_id=sid,
                        need_text=ev.need_text,
                        tokens=res.tokens,
                        key=res.need_key,
                        budget=res.budget,
                        language=cust.language,
                    )
            return {"simulated": body.count, "outcomes": outcomes}

        @app.post("/api/demo/reset", dependencies=owner)
        def demo_reset(request: Request):
            C(request).reset_demo()
            return {"ok": True}

    # ---- single-page app ---------------------------------------------------------------------
    static = Path(settings.static_dir)
    if static.is_dir():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets") if (
            static / "assets"
        ).is_dir() else None

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            target = (static / path).resolve()
            if path and target.is_file() and static.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(static / "index.html")

    return app


def _valid_id(v: str) -> bool:
    import re

    return bool(re.fullmatch(ID_PATTERN, v))


app = create_app()
