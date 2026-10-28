import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api, getOpsKey, setOpsKey } from "../api";
import type { Audit, Plan, PurchaseOrder, Summary } from "../types";
import ForecastChart from "./ForecastChart";
import Reorders from "./Reorders";
import Shelf from "./Shelf";
import { Activity, Copilot, Simulator } from "./Tools";

const inr = (n: number) => `₹${Math.round(n).toLocaleString("en-IN")}`;

function Ledger({ s }: { s: Summary }) {
  const rate = s.fulfilment_rate == null ? "—" : `${Math.round(s.fulfilment_rate * 100)}%`;
  return (
    <dl className="ledger" aria-label="Last 7 days">
      <div><dt>Shoppers served</dt><dd>{rate}<small>{s.fulfilled} of {s.queries} requests</small></dd></div>
      <div><dt>Turned away</dt><dd>{s.unmet_shoppers}<small>{s.open_needs} different needs</small></dd></div>
      <div className="hot"><dt>Sales at risk</dt><dd>{inr(s.revenue_at_risk)}<small>one purchase per shopper</small></dd></div>
      <div><dt>Waiting for news</dt><dd>{s.waitlist_open}<small>{s.waitlist_recovered} already messaged</small></dd></div>
      <div><dt>Urgent reorders</dt><dd>{s.critical_reorders}<small>{s.low_stock_skus} {s.low_stock_skus === 1 ? "item" : "items"} nearly out</small></dd></div>
    </dl>
  );
}

export default function Owner({ demo }: { demo: boolean }) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [pos, setPos] = useState<PurchaseOrder[]>([]);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [sku, setSku] = useState("G-RICE-BAS-5");
  const [authErr, setAuthErr] = useState(false);
  const [err, setErr] = useState("");
  const [keyDraft, setKeyDraft] = useState(getOpsKey());

  const load = useCallback(async () => {
    try {
      const [s, p, o, a] = await Promise.all([api.summary(), api.plan(), api.pos(), api.audit()]);
      setSummary(s);
      setPlan(p);
      setPos(o.purchase_orders);
      setAudit(a.audit);
      setAuthErr(false);
      setErr("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setAuthErr(true);
      else setErr(e instanceof Error ? e.message : "Couldn't load owner data");
    }
  }, []);

  useEffect(() => {
    void load();
    const t = window.setInterval(load, 8000);
    window.addEventListener("shelfsense:changed", load);
    return () => {
      window.clearInterval(t);
      window.removeEventListener("shelfsense:changed", load);
    };
  }, [load]);

  const names = useMemo(() => Object.fromEntries((plan?.reorders ?? []).map((r) => [r.sku, r.name])), [plan]);

  if (authErr)
    return (
      <section className="panel auth">
        <h2>Owner console is locked</h2>
        <p>Enter the owner key set in <code>OPS_API_KEY</code> to continue.</p>
        <form className="composer" onSubmit={(e) => { e.preventDefault(); setOpsKey(keyDraft); void load(); }}>
          <input type="password" value={keyDraft} onChange={(e) => setKeyDraft(e.target.value)} placeholder="Owner key" aria-label="Owner key" />
          <button className="btn btn-primary">Unlock</button>
        </form>
      </section>
    );

  if (err) return <p className="err" role="alert">Couldn't load owner data: {err}. Is the API running?</p>;
  if (!summary || !plan) return <p className="empty">Loading your store…</p>;

  return (
    <div className="owner">
      <Ledger s={summary} />
      <Shelf items={plan.opportunities} />
      <div className="grid2 wide-left">
        <Reorders items={plan.reorders} pos={pos} onPick={setSku} picked={sku} />
        <section className="panel" aria-labelledby="fc-h">
          <header className="panel-head">
            <div>
              <h2 id="fc-h">Demand forecast</h2>
              <p>Pick an item from the reorder list to see how its order was worked out.</p>
            </div>
          </header>
          <ForecastChart sku={sku} names={names} />
        </section>
      </div>
      <div className="grid2">
        <Copilot />
        <div className="stack">
          <Activity items={audit} />
          <Simulator demo={demo} />
        </div>
      </div>
    </div>
  );
}
