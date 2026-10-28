"""Shopper-side logic shared by the deterministic engine and the Gemini agent's tools.

``search_and_log`` is the single place a shopper need is searched *and* recorded as a demand signal.
Instrumentation lives in code, not in the prompt, so no conversation can ever skip it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .domain import Customer, DemandEvent, Match, Outcome, SearchResult, WaitlistEntry, utcnow
from .i18n import msg
from .services.catalog import CatalogService
from .services.demand import DemandService
from .store import Repo
from .textutil import detect_language, is_affirmative, is_greeting, is_negative, scrub_pii

SUPPORTED = ("en", "hi", "te")


class TraceStep(BaseModel):
    agent: str
    action: str
    detail: str = ""


class ChatReply(BaseModel):
    reply: str
    language: str = "en"
    outcome: Outcome | None = None
    products: list[Match] = Field(default_factory=list)
    substitutes: list[Match] = Field(default_factory=list)
    offer: dict | None = None  # {"need": str} when the assistant asks for waitlist consent
    waitlisted: bool = False
    trace: list[TraceStep] = Field(default_factory=list)
    engine: str = "offline"  # offline | gemini | offline-fallback
    session_id: str = ""


class SessionState(BaseModel):
    id: str
    language: str = "en"
    pending: dict | None = None
    updated: datetime = Field(default_factory=utcnow)


class ShopperEngine:
    def __init__(
        self,
        catalog: CatalogService,
        demand: DemandService,
        customers: Repo[Customer],
        sessions: Repo[SessionState],
    ) -> None:
        self.catalog, self.demand, self.customers, self.sessions = catalog, demand, customers, sessions

    # ---- shared primitives (also used as agent tools) -------------------------------------
    def ensure_customer(self, customer_id: str, language: str = "en", channel: str = "web") -> Customer:
        c = self.customers.get(customer_id)
        if c is None:
            c = Customer(id=customer_id, name="there", language=language, channel=channel)
            self.customers.put(c)
        return c

    def search_and_log(
        self,
        *,
        customer_id: str,
        session_id: str,
        text: str,
        need_text: str | None,
        language: str,
        max_price: float | None = None,
        channel: str = "web",
        ts: datetime | None = None,
    ) -> tuple[SearchResult, DemandEvent]:
        query = need_text or text
        res = self.catalog.search(query, max_price=max_price)
        ev = self.demand.log(
            customer_id=customer_id,
            session_id=session_id,
            text=text,
            need_text=_clean_need(query),
            language=language,
            result=res,
            channel=channel,
            ts=ts,
        )
        return res, ev

    def set_pending(self, session_id: str, res: SearchResult, need_text: str, language: str) -> None:
        sess = self.sessions.get(session_id) or SessionState(id=session_id)
        sess.language = language
        sess.updated = utcnow()
        sess.pending = (
            None
            if res.outcome is Outcome.IN_STOCK or not res.tokens
            else {
                "need_text": _clean_need(need_text),
                "tokens": res.tokens,
                "key": res.need_key,
                "budget": res.budget,
                "language": language,
            }
        )
        self.sessions.put(sess)

    def confirm_waitlist(self, customer_id: str, session_id: str) -> WaitlistEntry | None:
        """Join the waitlist for the session's pending offer. Only called after an explicit 'yes'."""
        sess = self.sessions.get(session_id)
        if not sess or not sess.pending:
            return None
        p = sess.pending
        entry = self.demand.join_waitlist(
            customer_id=customer_id,
            session_id=session_id,
            need_text=p["need_text"],
            tokens=p["tokens"],
            key=p["key"],
            budget=p.get("budget"),
            language=p["language"],
        )
        c = self.customers.get(customer_id)
        if c and not c.consent_notify:
            c.consent_notify = True  # explicit, per-request opt-in recorded on the profile
            self.customers.put(c)
        sess.pending = None
        self.sessions.put(sess)
        return entry

    # ---- deterministic conversation (offline mode & degraded-mode fallback) -----------------
    def reply(
        self,
        *,
        customer_id: str,
        session_id: str,
        text: str,
        language_hint: str | None = None,
        channel: str = "web",
    ) -> ChatReply:
        sess = self.sessions.get(session_id) or SessionState(id=session_id)
        lang = self._language(text, language_hint, sess)
        cust = self.ensure_customer(customer_id, lang, channel)
        trace = [TraceStep(agent="Conversation", action="understand", detail=f"language={lang}")]

        if sess.pending and is_affirmative(text):
            need = sess.pending["need_text"]
            self.confirm_waitlist(customer_id, session_id)
            trace.append(
                TraceStep(agent="Outreach", action="waitlist.join", detail=f"consented; need='{need}'")
            )
            return ChatReply(
                reply=msg(lang, "waitlisted", need=need),
                language=lang,
                waitlisted=True,
                trace=trace,
                session_id=session_id,
            )
        if sess.pending and is_negative(text):
            sess.pending, sess.language = None, lang
            self.sessions.put(sess)
            trace.append(TraceStep(agent="Conversation", action="offer.declined"))
            return ChatReply(reply=msg(lang, "declined"), language=lang, trace=trace, session_id=session_id)
        if is_greeting(text):
            name = cust.name if cust.name != "there" else ("" if lang != "en" else "there")
            return ChatReply(
                reply=msg(lang, "greeting", name=name).replace("  ", " ").replace(" !", "!"),
                language=lang,
                trace=trace,
                session_id=session_id,
            )

        res, ev = self.search_and_log(
            customer_id=customer_id,
            session_id=session_id,
            text=text,
            need_text=None,
            language=lang,
            channel=channel,
        )
        trace.append(
            TraceStep(
                agent="Catalog",
                action="search",
                detail=f"outcome={res.outcome.value} coverage={res.coverage:.2f} budget={res.budget}",
            )
        )
        trace.append(
            TraceStep(
                agent="Demand-Signal",
                action="log",
                detail=f"{'unmet' if res.outcome.is_unmet else 'fulfilled'} need recorded ({ev.id})",
            )
        )
        self.set_pending(session_id, res, _clean_need(text), lang)
        need = _clean_need(text)
        offer = None if res.outcome is Outcome.IN_STOCK else {"need": need}
        if offer:
            trace.append(
                TraceStep(agent="Conversation", action="offer.waitlist", detail="asked for consent to notify")
            )
        return ChatReply(
            reply=self._compose(res, need, lang),
            language=lang,
            outcome=res.outcome,
            products=res.exact,
            substitutes=res.substitutes,
            offer=offer,
            trace=trace,
            session_id=session_id,
        )

    @staticmethod
    def _language(text: str, hint: str | None, sess: SessionState) -> str:
        if hint in SUPPORTED:
            return hint  # type: ignore[return-value]
        det = detect_language(text)
        if det == "en" and sess.language != "en" and len(text.split()) <= 3:
            return sess.language  # short replies like "yes" inherit the conversation language
        return det

    @staticmethod
    def _items(ms: list[Match], n: int = 3) -> str:
        return "; ".join(f"{m.name} (₹{m.price:.0f})" for m in ms[:n])

    def _compose(self, res: SearchResult, need: str, lang: str) -> str:
        it = self._items
        if res.outcome is Outcome.IN_STOCK:
            return msg(lang, "in_stock", items=it(res.exact))
        if res.outcome is Outcome.OUT_OF_STOCK:
            text = msg(lang, "out_of_stock", items=it(res.exact, 1))
            if res.substitutes:
                text = msg(lang, "alt", items=it(res.substitutes, 2)) + " " + text
            return text
        if res.outcome is Outcome.OVER_BUDGET:
            return msg(lang, "over_budget", items=it(res.exact, 1), budget=res.budget or 0)
        if res.outcome is Outcome.PARTIAL and res.substitutes:
            return msg(lang, "partial", need=need, items=it(res.substitutes, 2))
        return msg(lang, "not_carried", need=need)


def _clean_need(text: str) -> str:
    from .textutil import parse_budget

    _b, stripped = parse_budget(scrub_pii(text))
    return " ".join(stripped.split()).strip(" .?!,;")[:120]
