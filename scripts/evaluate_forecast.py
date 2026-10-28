"""Print the forecast backtest the README quotes: model vs. seasonal-naive vs. moving-average WAPE."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from shelfsense.seed import build_sales  # noqa: E402
from shelfsense.services.forecast import ForecastService, MemorySales  # noqa: E402

sales = build_sales()
print(json.dumps(ForecastService(MemorySales(sales), 0.5).fleet_backtest(list(sales)), indent=2))
