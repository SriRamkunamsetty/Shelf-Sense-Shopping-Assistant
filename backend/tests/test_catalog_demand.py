import pytest

from shelfsense.domain import Outcome


@pytest.mark.parametrize(
    "query,outcome",
    [
        ("sugar", Outcome.IN_STOCK),
        ("mujhe chini chahiye", Outcome.IN_STOCK),
        ("చక్కెర కావాలి", Outcome.IN_STOCK),
        ("basmati rice 5kg", Outcome.OUT_OF_STOCK),
        ("wireless earbuds under 1000", Outcome.OVER_BUDGET),
        ("wireless earbuds under 2000", Outcome.IN_STOCK),
        ("gluten free pasta", Outcome.PARTIAL),
        ("millet cookies", Outcome.PARTIAL),
        ("quantum flux capacitor", Outcome.NOT_CARRIED),
    ],
)
def test_outcome_classification(ctx, query, outcome):
    assert ctx.catalog.search(query).outcome is outcome


def test_search_never_returns_unrelated_items_as_exact(ctx):
    res = ctx.catalog.search("gluten free pasta")
    assert res.exact == [] and all(m.coverage < 0.75 for m in res.substitutes)


def test_variants_cluster_together(ctx):
    labels = {c.label: c for c in ctx.demand.clusters(days=14)}
    pasta = next(c for lab, c in labels.items() if "pasta" in lab)
    # "gluten free pasta" and "gluten free penne pasta under 300" are one need, not two
    assert pasta.events >= 9 and pasta.unique_customers >= 5
    millet = next(c for lab, c in labels.items() if "millet" in lab or "ragi" in lab or "cookie" in lab)
    assert millet.events >= 5  # ragi biscuits + millet cookies merged via synonym


def test_fulfilled_needs_are_not_unmet_demand(ctx):
    labels = [c.label for c in ctx.demand.clusters(days=14)]
    assert not any(lab in ("sugar", "toned milk", "atta") for lab in labels)


def test_summary_is_consistent(ctx):
    s = ctx.demand.summary(days=7)
    assert s["queries"] == s["fulfilled"] + s["unmet"]
    assert 0 < s["fulfilment_rate"] < 1 and s["revenue_at_risk"] > 0


def test_events_are_pii_scrubbed(ctx):
    res, ev = ctx.shopper.search_and_log(
        customer_id="c001",
        session_id="s",
        text="gluten free pasta call 9876543210",
        need_text=None,
        language="en",
    )
    assert "9876543210" not in ev.text and "9876543210" not in ev.need_text
