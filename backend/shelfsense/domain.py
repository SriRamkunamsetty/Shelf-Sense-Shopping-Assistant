"""Domain models shared by services, agents and the HTTP API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


class Outcome(StrEnum):
    """What happened to a shopper's need. Everything except IN_STOCK is *unmet demand*."""

    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"  # we carry it, but none on the shelf
    OVER_BUDGET = "over_budget"  # we carry it, but above the shopper's budget
    PARTIAL = "partial"  # only a close substitute exists
    NOT_CARRIED = "not_carried"  # nothing relevant in the catalogue

    @property
    def is_unmet(self) -> bool:
        return self is not Outcome.IN_STOCK


class Product(BaseModel):
    sku: str
    name: str
    category: str
    brand: str = ""
    price: float
    cost: float
    stock: int = 0
    on_order: int = 0
    lead_time_days: int = 3
    pack_size: int = 1
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)  # synonyms / vernacular names
    attributes: dict[str, str] = Field(default_factory=dict)
    active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class Customer(BaseModel):
    id: str
    name: str = "Shopper"
    language: str = "en"  # en | hi | te
    channel: str = "web"
    consent_notify: bool = False  # explicit opt-in to be contacted about availability


class DemandEvent(BaseModel):
    """One shopper need, captured at the moment it was expressed."""

    id: str = Field(default_factory=lambda: new_id("ev_"))
    ts: datetime = Field(default_factory=utcnow)
    customer_id: str
    session_id: str = ""
    text: str  # PII-scrubbed original utterance
    need_text: str  # canonical short English phrase for the need
    need_key: str  # sorted canonical tokens (clustering key)
    tokens: list[str] = Field(default_factory=list)
    language: str = "en"
    outcome: Outcome
    coverage: float = 0.0
    matched_skus: list[str] = Field(default_factory=list)
    budget: float | None = None
    est_value: float = 0.0  # estimated basket value of this need (INR)
    channel: str = "web"


class WaitlistEntry(BaseModel):
    id: str = Field(default_factory=lambda: new_id("wl_"))
    customer_id: str
    need_key: str
    need_text: str
    tokens: list[str] = Field(default_factory=list)
    budget: float | None = None
    language: str = "en"
    session_id: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    consent_at: datetime | None = None  # set only after the shopper explicitly says yes
    status: str = "waiting"  # waiting | notified | cancelled


class Notification(BaseModel):
    id: str = Field(default_factory=lambda: new_id("nt_"))
    customer_id: str
    waitlist_id: str
    sku: str
    product_name: str
    message: str
    language: str = "en"
    channel: str = "in_app"
    created_at: datetime = Field(default_factory=utcnow)
    delivered: bool = True
    read: bool = False


class PurchaseOrder(BaseModel):
    id: str = Field(default_factory=lambda: new_id("po_"))
    sku: str
    qty: int
    unit_cost: float
    status: str = "approved"  # approved | received | cancelled
    created_at: datetime = Field(default_factory=utcnow)
    expected_at: datetime | None = None
    received_at: datetime | None = None
    approved_by: str = "owner"
    note: str = ""


class AuditRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("au_"))
    ts: datetime = Field(default_factory=utcnow)
    actor: str
    action: str
    details: dict = Field(default_factory=dict)


# --- read models returned by services ---------------------------------------------------------


class Match(BaseModel):
    sku: str
    name: str
    price: float
    stock: int
    category: str
    coverage: float
    in_stock: bool


class SearchResult(BaseModel):
    query: str
    tokens: list[str]
    budget: float | None
    outcome: Outcome
    coverage: float  # best coverage observed
    exact: list[Match] = Field(default_factory=list)
    substitutes: list[Match] = Field(default_factory=list)
    need_key: str = ""
    est_value: float = 0.0


class NeedCluster(BaseModel):
    cluster_id: str
    label: str
    tokens: list[str]
    events: int
    unique_customers: int
    outcomes: dict[str, int]
    dominant_outcome: Outcome
    median_budget: float | None = None
    est_unit_value: float = 0.0
    revenue_at_risk: float = 0.0
    first_seen: datetime
    last_seen: datetime
    events_7d: int
    events_prev_7d: int
    trend_pct: float | None = None  # None when there is no prior-week baseline
    languages: dict[str, int] = Field(default_factory=dict)
    waitlist_count: int = 0
    sample_queries: list[str] = Field(default_factory=list)
    nearest_skus: list[str] = Field(default_factory=list)
    priority: float = 0.0


class ForecastPoint(BaseModel):
    date: str
    mean: float
    lo: float
    hi: float


class ForecastResult(BaseModel):
    sku: str
    name: str
    method: str
    horizon_days: int
    history: list[dict]  # [{date, units, corrected, in_stock}]
    forecast: list[ForecastPoint]
    daily_mean: float
    daily_sigma: float
    lost_units_estimate: float
    signal_uplift_per_day: float
    wape_model: float | None = None
    wape_seasonal_naive: float | None = None
    wape_moving_avg: float | None = None


class ReorderRec(BaseModel):
    sku: str
    name: str
    stock: int
    on_order: int
    lead_time_days: int
    days_of_cover: float | None
    forecast_next_7d: float
    safety_stock: int
    reorder_qty: int
    unit_cost: float
    order_cost: float
    revenue_protected: float
    priority: str  # critical | high | normal
    rationale: str


class Opportunity(BaseModel):
    cluster_id: str
    kind: str  # new_listing | restock | price_gap
    label: str
    unique_customers: int
    events: int
    trend_pct: float | None
    confidence: str  # low | medium | high
    est_weekly_units: float
    suggested_name: str
    suggested_price: float
    suggested_qty: int
    revenue_at_risk: float
    linked_sku: str | None = None
    nearest_skus: list[str] = Field(default_factory=list)
    waitlist_count: int = 0
    action: str
    rationale: str


class RestockPlan(BaseModel):
    generated_at: datetime
    reorders: list[ReorderRec]
    opportunities: list[Opportunity]
    total_order_cost: float
    total_revenue_at_risk: float
