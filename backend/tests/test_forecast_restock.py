from datetime import date, timedelta

from shelfsense.seed import DayRecord
from shelfsense.services.forecast import ForecastService, MemorySales, correct_stockouts, predict


def _series(n=60, base=10.0, out=(), start=date(2026, 8, 1)):
    return [
        (
            start + timedelta(days=i),
            0 if i in out else int(base + (3 if (start + timedelta(days=i)).weekday() >= 5 else 0)),
            i not in out,
        )
        for i in range(n)
    ]


def test_stockout_days_are_imputed_not_treated_as_zero_demand():
    rows = _series(out=range(50, 60))
    y, lost = correct_stockouts(rows)
    assert min(y[50:]) >= 9 and lost > 80  # demand recovered from same-weekday history


def test_forecast_after_stockout_is_not_collapsed(ctx):
    # Basmati rice is out of stock for the last 5 days in the seed; a naive model would forecast ~0
    p = ctx.catalog.get("G-RICE-BAS-5")
    f = ctx.forecast.forecast(p, horizon=7)
    assert f.lost_units_estimate > 5 and f.daily_mean > 3


def test_holt_winters_learns_weekly_pattern():
    rows = _series(n=70)
    y = [float(u) for _d, u, _s in rows]
    fc, _sigma, method = predict(y, 7)
    assert method.startswith("holt-winters")
    # weekend (index 5,6 from a Saturday-aligned start) must forecast higher than weekdays
    start = rows[-1][0] + timedelta(days=1)
    weekend = [v for k, v in enumerate(fc) if (start + timedelta(days=k)).weekday() >= 5]
    weekday = [v for k, v in enumerate(fc) if (start + timedelta(days=k)).weekday() < 5]
    assert min(weekend) > max(weekday)


def test_short_history_degrades_gracefully():
    fc, _s, method = predict([5.0, 6.0, 4.0, 5.0], 3)
    assert method == "moving-average" and len(fc) == 3
    assert predict([], 2)[2] == "no-data"


def test_model_beats_seasonal_naive_on_fleet(ctx):
    ev = ctx.forecast.fleet_backtest([p.sku for p in ctx.catalog.all_products()])
    assert ev["skus"] >= 30 and ev["model"] < ev["seasonal_naive"]


def test_signal_uplift_raises_forecast(ctx):
    p = ctx.catalog.get("G-RICE-BAS-5")
    base = ForecastService(ctx.sales, 0.5).forecast(p, horizon=7).daily_mean
    boosted = (
        ForecastService(ctx.sales, 0.5, unmet_lookup=lambda: {p.sku: 14}).forecast(p, horizon=7).daily_mean
    )
    assert boosted > base + 0.5


def test_reorders_flag_empty_shelf_as_critical_and_respect_pack_size(ctx):
    recs = {r.sku: r for r in ctx.restock.reorders()}
    rice = recs["G-RICE-BAS-5"]
    assert rice.priority == "critical" and rice.reorder_qty % ctx.catalog.get("G-RICE-BAS-5").pack_size == 0
    assert recs["G-RICE-BAS-5"].reorder_qty > 0 and "stock" in rice.rationale.lower()


def test_well_stocked_items_are_not_reordered(ctx):
    skus = {r.sku for r in ctx.restock.reorders()}
    assert "G-SUGAR-1" not in skus and len(skus) < len(ctx.catalog.all_products()) / 2


def test_on_order_stock_counts_toward_position(ctx):
    before = {r.sku: r for r in ctx.restock.reorders()}["G-RICE-BAS-5"].reorder_qty
    ctx.inventory.approve_po("G-RICE-BAS-5", before)
    after = {r.sku: r for r in ctx.restock.reorders()}.get("G-RICE-BAS-5")
    assert after is None or after.reorder_qty < before


def test_opportunity_kinds(ctx):
    kinds = {o.label: o.kind for o in ctx.restock.opportunities()}
    assert kinds["gluten free pasta"] == "new_listing"
    assert kinds["wireless earbuds"] == "price_gap"
    assert kinds["basmati rice 5kg"] == "restock"


def test_sales_repo_roundtrip():
    s = MemorySales({"x": [DayRecord(date(2026, 1, 1), 3, True)]})
    s.append_day("x", date(2026, 1, 2), 4)
    assert [u for _d, u, _ok in s.daily("x")] == [3, 4]
