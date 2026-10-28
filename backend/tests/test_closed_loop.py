"""The headline scenario: shopper asks -> unmet -> consents -> owner fulfils -> shopper is notified."""

from shelfsense.domain import Outcome


def _ask(ctx, text, cid="c010", sid="loop-1", lang=None):
    return ctx.shopper.reply(customer_id=cid, session_id=sid, text=text, language_hint=lang)


def test_full_loop_english(ctx):
    r1 = _ask(ctx, "gluten free pasta under 300")
    assert r1.outcome is Outcome.PARTIAL and r1.offer and r1.substitutes
    r2 = _ask(ctx, "yes please")
    assert r2.waitlisted

    prod, notes = ctx.inventory.list_new_product(name="Gluten Free Pasta 400g", price=280, qty=24)
    mine = [n for n in notes if n.customer_id == "c010"]
    assert mine and prod.name in mine[0].message and "280" in mine[0].message
    assert ctx.outreach.inbox("c010")[0].sku == prod.sku
    # and the need is now fulfilled for new shoppers
    assert ctx.catalog.search("gluten free pasta").outcome is Outcome.IN_STOCK


def test_notification_is_in_the_shoppers_language(ctx):
    _ask(ctx, "నాకు gluten free pasta కావాలి", cid="c011", sid="loop-te")
    assert _ask(ctx, "అవును", cid="c011", sid="loop-te").waitlisted
    _p, notes = ctx.inventory.list_new_product(name="Gluten Free Pasta 400g", price=250, qty=12)
    msg = next(n for n in notes if n.customer_id == "c011")
    assert msg.language == "te" and "శుభవార్త" in msg.message


def test_declining_creates_no_waitlist_entry(ctx):
    before = len(ctx.waitlist.list())
    _ask(ctx, "oat milk", cid="c012", sid="loop-no")
    r = _ask(ctx, "no thanks", cid="c012", sid="loop-no")
    assert not r.waitlisted and len(ctx.waitlist.list()) == before


def test_no_consent_no_message(ctx):
    _ask(ctx, "gluten free pasta", cid="c013", sid="loop-nc")
    # entry exists only after explicit yes; simulate a legacy entry without consent timestamp
    e = ctx.demand.join_waitlist(
        customer_id="c013",
        session_id="x",
        need_text="gluten free pasta",
        tokens=["glutenfree", "pasta"],
        key="glutenfree pasta",
        budget=None,
        language="en",
    )
    e.consent_at = None
    ctx.waitlist.put(e)
    _p, notes = ctx.inventory.list_new_product(name="Gluten Free Pasta", price=250, qty=12)
    assert all(n.customer_id != "c013" for n in notes)


def test_budget_is_respected_when_notifying(ctx):
    _ask(ctx, "wireless earbuds under 1000", cid="c014", sid="loop-b")
    assert _ask(ctx, "yes", cid="c014", sid="loop-b").waitlisted
    # a restock at the old (too high) price must not ping this shopper
    _p, notes = ctx.inventory.receive_stock("E-EAR-TWS", 5)
    assert all(n.customer_id != "c014" for n in notes)


def test_waitlist_join_is_idempotent(ctx):
    for sid in ("a", "b"):
        _ask(ctx, "oat milk", cid="c015", sid=f"idem-{sid}")
        _ask(ctx, "yes", cid="c015", sid=f"idem-{sid}")
    assert len([w for w in ctx.waitlist.list({"customer_id": "c015"}) if w.status == "waiting"]) == 1


def test_po_lifecycle_updates_stock_and_audit(ctx):
    po = ctx.inventory.approve_po("G-RICE-BAS-5", 60)
    assert ctx.catalog.get("G-RICE-BAS-5").on_order == 60
    _ask(ctx, "basmati rice 5kg", cid="c016", sid="po-1")
    _ask(ctx, "yes", cid="c016", sid="po-1")
    po2, notes = ctx.inventory.receive_po(po.id)
    p = ctx.catalog.get("G-RICE-BAS-5")
    assert po2.status == "received" and p.stock == 60 and p.on_order == 0
    assert any(n.customer_id == "c016" for n in notes)
    assert {"po.approve", "po.receive"} <= {a.action for a in ctx.audit.list()}


def test_rejoining_updates_language_to_latest_conversation(ctx):
    # seeded customers may already be waiting in another language; the newest conversation wins
    e = ctx.demand.join_waitlist(
        customer_id="c040",
        session_id="s1",
        need_text="oat milk",
        tokens=["milk", "oat"],
        key="milk oat",
        budget=None,
        language="te",
        audit=False,
    )
    assert e.language == "te"
    again = ctx.demand.join_waitlist(
        customer_id="c040",
        session_id="s2",
        need_text="oat milk",
        tokens=["milk", "oat"],
        key="milk oat",
        budget=None,
        language="en",
    )
    assert again.id == e.id and again.language == "en"


def test_trend_is_hidden_for_tiny_baselines(ctx):
    assert all(c.trend_pct is None or c.events_prev_7d >= 3 for c in ctx.demand.clusters(days=14))
