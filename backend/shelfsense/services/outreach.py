"""Closing the loop: when a need becomes fulfillable, tell the shoppers who asked — with consent."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

import httpx

from ..domain import Customer, Notification, Product, WaitlistEntry, utcnow
from ..store import Repo
from .catalog import CatalogService

log = logging.getLogger("shelfsense.outreach")

TEMPLATES = {
    "en": "Good news, {name}! {product} is now available for ₹{price:.0f}. You asked us about “{need}” — grab it before it sells out.",
    "hi": "खुशखबरी {name}! {product} अब ₹{price:.0f} में उपलब्ध है। आपने “{need}” के बारे में पूछा था।",
    "te": "శుభవార్త {name}! {product} ఇప్పుడు ₹{price:.0f} కు అందుబాటులో ఉంది. మీరు “{need}” గురించి అడిగారు.",
}


class Channel(Protocol):
    name: str

    def send(self, note: Notification) -> bool: ...


class InAppChannel:
    """Notifications are persisted and shown in the shopper's inbox (always on)."""

    name = "in_app"

    def send(self, note: Notification) -> bool:
        return True


class WebhookChannel:
    """POSTs each notification to a URL — the hook for a WhatsApp Business / SMS / push bridge."""

    name = "webhook"

    def __init__(self, url: str, timeout: float = 5.0) -> None:
        self.url, self.timeout = url, timeout

    def send(self, note: Notification) -> bool:
        try:
            r = httpx.post(self.url, json=note.model_dump(mode="json"), timeout=self.timeout)
            return r.is_success
        except httpx.HTTPError as exc:
            log.warning("webhook delivery failed: %s", exc)
            return False


class OutreachService:
    def __init__(
        self,
        catalog: CatalogService,
        waitlist: Repo[WaitlistEntry],
        customers: Repo[Customer],
        notifications: Repo[Notification],
        channels: list[Channel] | None = None,
        clock: Callable[[], datetime] = utcnow,
        full_coverage: float = 0.75,
    ) -> None:
        self.catalog, self.waitlist, self.customers, self.notifications = (
            catalog,
            waitlist,
            customers,
            notifications,
        )
        self.channels = channels or [InAppChannel()]
        self.clock, self.full = clock, full_coverage

    def matches(self, product: Product) -> list[WaitlistEntry]:
        """Waiting, consented entries whose need this product fully covers and fits the budget."""
        if product.stock <= 0:
            return []
        out = []
        for w in self.waitlist.list({"status": "waiting"}):
            if w.consent_at is None:
                continue
            if w.budget is not None and product.price > w.budget:
                continue
            if self.catalog.coverage(w.tokens, product.sku) >= self.full:
                out.append(w)
        return out

    def notify_for_product(self, product: Product) -> list[Notification]:
        sent: list[Notification] = []
        for w in self.matches(product):
            cust = self.customers.get(w.customer_id) or Customer(id=w.customer_id)
            lang = w.language if w.language in TEMPLATES else "en"
            msg = TEMPLATES[lang].format(
                name=cust.name, product=product.name, price=product.price, need=w.need_text
            )
            note = Notification(
                customer_id=w.customer_id,
                waitlist_id=w.id,
                sku=product.sku,
                product_name=product.name,
                message=msg,
                language=lang,
                created_at=self.clock(),
            )
            for ch in self.channels:
                try:
                    ok = ch.send(note)
                except Exception:
                    log.exception("channel %s failed", ch.name)
                    ok = False
                if ok and ch.name != "in_app":
                    note.channel += f"+{ch.name}"
            self.notifications.put(note)
            w.status = "notified"
            self.waitlist.put(w)
            sent.append(note)
        return sent

    def inbox(self, customer_id: str) -> list[Notification]:
        return sorted(
            self.notifications.list({"customer_id": customer_id}), key=lambda n: n.created_at, reverse=True
        )

    def mark_read(self, customer_id: str) -> None:
        for n in self.notifications.list({"customer_id": customer_id}):
            if not n.read:
                n.read = True
                self.notifications.put(n)
