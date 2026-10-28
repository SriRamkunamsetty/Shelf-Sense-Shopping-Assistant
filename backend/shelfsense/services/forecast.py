"""Demand forecasting.

Pipeline per SKU:
 1. **Stock-out correction** — days where the shelf was empty under-report demand (censored data).
    They are re-estimated from the same weekday's in-stock history so a stock-out does not teach the
    model that demand collapsed.
 2. **Damped-trend Holt-Winters** (additive, weekly seasonality), parameters chosen by a small grid
    search on one-step-ahead error. Pure-Python so it runs anywhere with zero native dependencies.
 3. **Signal uplift** — shoppers recently turned away for this SKU (from ``DemandService``) are added
    as expected extra demand, so the plan reacts to *wanted* demand, not just *recorded* sales.
 4. **Backtest** — rolling hold-out WAPE against seasonal-naive and moving-average baselines, exposed
    in the API so the model can be audited rather than trusted.

For fleet-scale forecasting the same interface can be backed by BigQuery ML ``ARIMA_PLUS`` (see
``sql/bqml_forecast.sql``) or Vertex AI Forecast.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from datetime import date, timedelta
from typing import Protocol

from ..domain import ForecastPoint, ForecastResult, Product

SEASON = 7
PHI = 0.95  # trend damping
Z80 = 1.2816


class SalesRepository(Protocol):
    def daily(self, sku: str) -> list[tuple[date, int, bool]]: ...


class MemorySales:
    def __init__(self, data: dict[str, list]) -> None:
        self._data = data

    def daily(self, sku: str) -> list[tuple[date, int, bool]]:
        return [(r.day, r.units, r.in_stock) for r in self._data.get(sku, [])]

    def append_day(self, sku: str, day: date, units: int, in_stock: bool = True) -> None:
        from ..seed import DayRecord

        self._data.setdefault(sku, []).append(DayRecord(day, units, in_stock))


# --------------------------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------------------------


def correct_stockouts(rows: list[tuple[date, int, bool]]) -> tuple[list[float], float]:
    """Return demand series with stock-out days imputed, and total estimated lost units."""
    units = [float(u) for _d, u, _s in rows]
    out = list(units)
    lost = 0.0
    for i, (d, _u, ok) in enumerate(rows):
        if ok:
            continue
        same_dow = [units[j] for j, (dj, _uj, okj) in enumerate(rows) if okj and dj.weekday() == d.weekday()]
        if same_dow:
            base = statistics.fmean(same_dow[-6:])
        else:
            base = statistics.fmean([u for u, (_d, _x, k) in zip(units, rows, strict=True) if k] or [0.0])
        out[i] = max(base, units[i])
        lost += out[i] - units[i]
    return out, lost


def _hw_fit(y: list[float], a: float, b: float, g: float) -> tuple[float, float, list[float], list[float]]:
    m = SEASON
    level = statistics.fmean(y[:m])
    trend = (statistics.fmean(y[m : 2 * m]) - level) / m if len(y) >= 2 * m else 0.0
    seas = [y[i] - level for i in range(m)]
    resid: list[float] = []
    for t in range(m, len(y)):
        s = seas[t % m]
        fc = level + PHI * trend + s
        resid.append(y[t] - fc)
        new_level = a * (y[t] - s) + (1 - a) * (level + PHI * trend)
        trend = b * (new_level - level) + (1 - b) * PHI * trend
        seas[t % m] = g * (y[t] - new_level) + (1 - g) * s
        level = new_level
    return level, trend, seas, resid


def _hw_forecast(y: list[float], h: int, params: tuple[float, float, float]) -> tuple[list[float], float]:
    level, trend, seas, resid = _hw_fit(y, *params)
    n = len(y)
    out = []
    damp = 0.0
    for k in range(1, h + 1):
        damp += PHI**k
        out.append(max(0.0, level + damp * trend + seas[(n + k - 1) % SEASON]))
    sigma = statistics.pstdev(resid) if len(resid) > 2 else 0.0
    return out, sigma


def _best_params(y: list[float]) -> tuple[float, float, float]:
    best, best_sse = (0.2, 0.05, 0.2), float("inf")
    for a in (0.05, 0.15, 0.3, 0.5):
        for b in (0.0, 0.05, 0.15):
            for g in (0.05, 0.2, 0.4):
                *_x, resid = _hw_fit(y, a, b, g)
                sse = sum(r * r for r in resid)
                if sse < best_sse:
                    best, best_sse = (a, b, g), sse
    return best


def predict(y: list[float], h: int) -> tuple[list[float], float, str]:
    """Forecast ``h`` days ahead. Falls back gracefully for short histories."""
    if len(y) >= 3 * SEASON:
        fc, sigma = _hw_forecast(y, h, _best_params(y))
        return fc, sigma, "holt-winters(damped,weekly)"
    if len(y) >= 3:
        mu = statistics.fmean(y[-14:])
        return [mu] * h, statistics.pstdev(y[-14:]) if len(y) > 2 else 0.0, "moving-average"
    return [0.0] * h, 0.0, "no-data"


def wape(actual: list[float], fc: list[float]) -> float:
    tot = sum(actual)
    return sum(abs(a - f) for a, f in zip(actual, fc, strict=False)) / tot if tot else float("nan")


def backtest(y: list[float], holdout: int = 14) -> dict[str, float] | None:
    """Hold out the last ``holdout`` days; compare the model with two honest baselines."""
    if len(y) < holdout + 3 * SEASON:
        return None
    train, test = y[:-holdout], y[-holdout:]
    fc, _s, _m = predict(train, holdout)
    naive = [train[-SEASON + (i % SEASON)] for i in range(holdout)]
    ma = [statistics.fmean(train[-14:])] * holdout
    return {"model": wape(test, fc), "seasonal_naive": wape(test, naive), "moving_avg": wape(test, ma)}


# --------------------------------------------------------------------------------------------
# Service
# --------------------------------------------------------------------------------------------


class ForecastService:
    def __init__(
        self,
        sales: SalesRepository,
        capture_rate: float,
        unmet_lookup: Callable[[], dict[str, int]] | None = None,
    ) -> None:
        self.sales = sales
        self.capture = capture_rate
        self.unmet_lookup = unmet_lookup or (lambda: {})
        self._cache: dict[tuple[str, int, int], tuple[list[float], float, str, float]] = {}

    def _model(self, sku: str, h: int) -> tuple[list[date], list[float], float, list[float], float, str]:
        rows = self.sales.daily(sku)
        y, lost = correct_stockouts(rows)
        key = (sku, len(rows), h)
        if key not in self._cache:
            fc, sigma, method = predict(y, h)
            self._cache[key] = (fc, sigma, method, lost)
        fc, sigma, method, lost = self._cache[key]
        return [r[0] for r in rows], y, lost, fc, sigma, method

    def forecast(
        self, p: Product, horizon: int = 14, history_days: int = 35, with_backtest: bool = False
    ) -> ForecastResult:
        dates, y, lost, fc, sigma, method = self._model(p.sku, horizon)
        raw = self.sales.daily(p.sku)
        uplift = (self.unmet_lookup().get(p.sku, 0) / 7.0) * self.capture
        last_day = dates[-1] if dates else date.today()
        points = []
        for k, v in enumerate(fc, start=1):
            mean = v + uplift
            spread = Z80 * sigma * math.sqrt(1 + (k - 1) * 0.03)
            points.append(
                ForecastPoint(
                    date=(last_day + timedelta(days=k)).isoformat(),
                    mean=round(mean, 2),
                    lo=round(max(0.0, mean - spread), 2),
                    hi=round(mean + spread, 2),
                )
            )
        bt = backtest(y) if with_backtest else None
        return ForecastResult(
            sku=p.sku,
            name=p.name,
            method=method,
            horizon_days=horizon,
            history=[
                {"date": d.isoformat(), "units": u, "corrected": round(c, 2), "in_stock": ok}
                for (d, u, ok), c in list(zip(raw, y, strict=True))[-history_days:]
            ],
            forecast=points,
            daily_mean=round(statistics.fmean([pt.mean for pt in points]), 3) if points else 0.0,
            daily_sigma=round(sigma, 3),
            lost_units_estimate=round(lost, 1),
            signal_uplift_per_day=round(uplift, 3),
            wape_model=round(bt["model"], 4) if bt else None,
            wape_seasonal_naive=round(bt["seasonal_naive"], 4) if bt else None,
            wape_moving_avg=round(bt["moving_avg"], 4) if bt else None,
        )

    def fleet_backtest(self, skus: list[str]) -> dict:
        rows = []
        for sku in skus:
            y, _ = correct_stockouts(self.sales.daily(sku))
            bt = backtest(y)
            if bt and not any(math.isnan(v) for v in bt.values()):
                rows.append(bt)
        if not rows:
            return {}
        agg = {k: round(statistics.fmean(r[k] for r in rows), 4) for k in rows[0]}
        agg["skus"] = len(rows)
        agg["improvement_vs_seasonal_naive_pct"] = round((1 - agg["model"] / agg["seasonal_naive"]) * 100, 1)
        agg["improvement_vs_moving_avg_pct"] = round((1 - agg["model"] / agg["moving_avg"]) * 100, 1)
        return agg
