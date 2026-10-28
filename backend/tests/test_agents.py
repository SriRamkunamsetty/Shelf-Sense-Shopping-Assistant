"""Exercises the real Google ADK Runner + tools with a scripted LLM (no network / credentials needed)."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.adk.tools import FunctionTool
from google.genai import types

from shelfsense.agents import tools
from shelfsense.agents.definitions import build_ops_copilot, build_shopper_agent, build_weekly_pipeline
from shelfsense.agents.runtime import AgentRuntime
from shelfsense.domain import Outcome


class ScriptedLlm(BaseLlm):
    """Behaves like a well-instructed Gemini: calls the right tool, then answers from the tool result."""

    model: str = "scripted"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        last = llm_request.contents[-1]
        part = last.parts[0]
        if part.function_response:
            name = part.function_response.name
            r = part.function_response.response or {}
            text = "You're on the list!" if name == "join_waitlist" else f"Result: {r.get('outcome')}"
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))
            return
        user = (part.text or "").lower()
        if user == "yes":
            call = types.FunctionCall(name="join_waitlist", args={})
        else:
            call = types.FunctionCall(
                name="search_catalog",
                args={
                    "query": "gluten free pasta",
                    "max_price": 300.0,
                    "original_text": user,
                    "language": "en",
                },
            )
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(function_call=call)]))


@pytest.mark.parametrize(
    "fn",
    [
        tools.search_catalog,
        tools.join_waitlist,
        tools.get_dashboard_summary,
        tools.get_unmet_demand_report,
        tools.forecast_sku,
        tools.get_restock_plan,
        tools.get_waitlist_matches,
    ],
)
def test_every_tool_has_a_valid_gemini_declaration(fn):
    decl = FunctionTool(fn)._get_declaration()
    assert decl.name == fn.__name__ and decl.description


def test_agent_graph_builds(ctx):
    assert build_shopper_agent("gemini-2.5-flash").name == "shopper_agent"
    ops = build_ops_copilot("gemini-2.5-flash")
    assert {t.name for t in ops.tools} >= {
        "demand_signal_agent",
        "forecast_agent",
        "inventory_agent",
        "outreach_agent",
    }
    assert [a.name for a in build_weekly_pipeline("gemini-2.5-flash").sub_agents] == [
        "demand_signal_agent",
        "forecast_agent",
        "inventory_agent",
        "outreach_agent",
    ]


async def test_shopper_agent_logs_signal_and_joins_waitlist(ctx):
    rt = AgentRuntime(ctx, model=ScriptedLlm())
    before = len(ctx.events.list())
    r1 = await rt.shopper_turn(
        customer_id="c030",
        session_id="adk-1",
        text="gluten free pasta under 300",
        language="en",
        channel="web",
    )
    assert r1.engine == "gemini" and r1.outcome is Outcome.PARTIAL and r1.offer
    assert len(ctx.events.list()) == before + 1  # instrumentation happened inside the tool
    assert any(t.action == "tool:search_catalog" for t in r1.trace)

    r2 = await rt.shopper_turn(
        customer_id="c030", session_id="adk-1", text="yes", language="en", channel="web"
    )
    assert r2.waitlisted and ctx.waitlist.list({"customer_id": "c030", "status": "waiting"})


async def test_join_waitlist_without_pending_offer_is_a_noop(ctx):
    rt = AgentRuntime(ctx, model=ScriptedLlm())
    r = await rt.shopper_turn(
        customer_id="c031", session_id="adk-2", text="yes", language="en", channel="web"
    )
    assert not r.waitlisted and not ctx.waitlist.list({"customer_id": "c031"})


def test_ops_tools_return_bounded_json(ctx):
    rep = tools.get_unmet_demand_report(days=14, top=3)
    assert len(rep["clusters"]) == 3 and "sample_queries" in rep["clusters"][0]
    assert tools.forecast_sku("NOPE")["error"]
    f = tools.forecast_sku("G-SUGAR-1", 7)
    assert f["wape_model"] is not None
    assert tools.get_restock_plan(2)["reorders"].__len__() == 2
