"""ADK runtime: sessions, runners and event parsing for the shopper agent and the ops copilot."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from ..domain import Match, Outcome
from ..shopper import ChatReply, TraceStep
from .definitions import build_ops_copilot, build_shopper_agent

if TYPE_CHECKING:
    from ..context import AppContext

log = logging.getLogger("shelfsense.agents")

AGENT_LABEL = {
    "shopper_agent": "Conversation",
    "ops_copilot": "Ops Copilot",
    "demand_signal_agent": "Demand-Signal",
    "forecast_agent": "Forecast",
    "inventory_agent": "Inventory",
    "outreach_agent": "Outreach",
}
TOOL_LABEL = {
    "search_catalog": "Catalog + Demand-Signal",
    "join_waitlist": "Outreach",
    "get_dashboard_summary": "Dashboard",
    "get_unmet_demand_report": "Demand-Signal",
    "forecast_sku": "Forecast",
    "get_restock_plan": "Inventory",
    "get_waitlist_matches": "Outreach",
}


@dataclass
class TurnResult:
    text: str = ""
    trace: list[TraceStep] = field(default_factory=list)
    tool_results: dict[str, list[dict]] = field(default_factory=dict)


class AgentRuntime:
    def __init__(self, ctx: AppContext, model: Any = None) -> None:
        self.ctx = ctx
        self.model = model or ctx.settings.gemini_model
        if ctx.settings.session_db_url:
            from google.adk.sessions import DatabaseSessionService

            self.sessions = DatabaseSessionService(db_url=ctx.settings.session_db_url)
        else:
            self.sessions = InMemorySessionService()
        self.shopper_runner = Runner(
            app_name="shelfsense-shopper",
            agent=build_shopper_agent(self.model),
            session_service=self.sessions,
        )
        self.ops_runner = Runner(
            app_name="shelfsense-ops", agent=build_ops_copilot(self.model), session_service=self.sessions
        )

    async def _ensure_session(self, app: str, user_id: str, session_id: str, state: dict) -> None:
        if await self.sessions.get_session(app_name=app, user_id=user_id, session_id=session_id) is None:
            await self.sessions.create_session(
                app_name=app, user_id=user_id, session_id=session_id, state=state
            )

    async def _run(
        self, runner: Runner, app: str, user_id: str, session_id: str, text: str, state: dict
    ) -> TurnResult:
        await self._ensure_session(app, user_id, session_id, state)
        out = TurnResult()
        msg = types.Content(role="user", parts=[types.Part(text=text)])
        async for ev in runner.run_async(user_id=user_id, session_id=session_id, new_message=msg):
            who = AGENT_LABEL.get(ev.author, ev.author)
            for fc in ev.get_function_calls() or []:
                out.trace.append(
                    TraceStep(agent=who, action=f"tool:{fc.name}", detail=_short(dict(fc.args or {})))
                )
            for fr in ev.get_function_responses() or []:
                resp = dict(fr.response or {})
                out.tool_results.setdefault(fr.name, []).append(resp)
                out.trace.append(
                    TraceStep(
                        agent=TOOL_LABEL.get(fr.name, who),
                        action=f"result:{fr.name}",
                        detail=_short(resp, 160),
                    )
                )
            if ev.is_final_response() and ev.content and ev.content.parts:
                out.text = "".join(p.text or "" for p in ev.content.parts if getattr(p, "text", None)).strip()
        return out

    async def shopper_turn(
        self, *, customer_id: str, session_id: str, text: str, language: str, channel: str
    ) -> ChatReply:
        self.ctx.shopper.ensure_customer(customer_id, language, channel)
        state = {"customer_id": customer_id, "session_id": session_id, "channel": channel}
        r = await self._run(self.shopper_runner, "shelfsense-shopper", customer_id, session_id, text, state)
        search = (r.tool_results.get("search_catalog") or [{}])[-1]
        joined = any(x.get("status") == "joined" for x in r.tool_results.get("join_waitlist", []))
        outcome = Outcome(search["outcome"]) if search.get("outcome") else None
        return ChatReply(
            reply=r.text or "Sorry, I couldn't process that. Could you rephrase?",
            language=language,
            outcome=outcome,
            products=[Match(**m) for m in search.get("products", [])],
            substitutes=[Match(**m) for m in search.get("substitutes", [])],
            offer={"need": search.get("need", "")} if search.get("offer_waitlist") and not joined else None,
            waitlisted=joined,
            trace=r.trace,
            engine="gemini",
            session_id=session_id,
        )

    async def ops_turn(self, *, session_id: str, text: str) -> tuple[str, list[TraceStep]]:
        r = await self._run(self.ops_runner, "shelfsense-ops", "owner", session_id, text, {})
        return r.text, r.trace


def _short(d: dict, n: int = 120) -> str:
    s = ", ".join(f"{k}={v}" for k, v in d.items())
    return s if len(s) <= n else s[: n - 1] + "…"
