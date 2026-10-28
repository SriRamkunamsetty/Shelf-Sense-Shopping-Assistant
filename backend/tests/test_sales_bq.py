from datetime import date

import pytest

from shelfsense.services.sales_bq import BigQuerySales


class FakeJob:
    def __init__(self, rows):
        self._rows = rows

    def result(self):
        return self._rows


class FakeClient:
    project = "proj"

    def __init__(self):
        self.calls = 0
        self.last_sql = ""

    def query(self, sql, job_config=None):
        self.calls += 1
        self.last_sql = sql
        params = {p.name: p.value for p in job_config.query_parameters}
        assert params == {"sku": "X1"}  # the SKU is a bound parameter, never string-formatted into SQL
        return FakeJob(
            [
                {"day": date(2026, 1, 1), "units": 4, "in_stock": True},
                {"day": date(2026, 1, 2), "units": 0, "in_stock": False},
            ]
        )


def test_reads_rows_with_bound_parameter_and_caches():
    c = FakeClient()
    s = BigQuerySales(None, "shelfsense", client=c)
    rows = s.daily("X1")
    assert rows == [(date(2026, 1, 1), 4, True), (date(2026, 1, 2), 0, False)]
    assert "proj.shelfsense.sales_daily" in c.last_sql and "@sku" in c.last_sql
    s.daily("X1")
    assert c.calls == 1


@pytest.mark.parametrize("bad", ["x`; DROP TABLE y; --", "a b", ""])
def test_dataset_name_is_validated(bad):
    with pytest.raises(ValueError):
        BigQuerySales("proj", bad, client=FakeClient())


def test_forecast_service_works_on_the_bigquery_repo_interface():
    from shelfsense.domain import Product
    from shelfsense.services.forecast import ForecastService

    class Many(FakeClient):
        def query(self, sql, job_config=None):
            from datetime import timedelta

            d0 = date(2026, 6, 1)
            return FakeJob(
                [{"day": d0 + timedelta(days=i), "units": 5 + (i % 7), "in_stock": True} for i in range(60)]
            )

    f = ForecastService(BigQuerySales("proj", "ds", client=Many()), 0.5)
    out = f.forecast(Product(sku="X1", name="X", category="c", price=10, cost=5), horizon=7)
    assert len(out.forecast) == 7 and out.method.startswith("holt-winters")
