import { useState } from "react";
import { api, notifyChanged } from "../api";
import type { FulfilResult, Opportunity } from "../types";

const KIND_LABEL: Record<Opportunity["kind"], string> = {
  new_listing: "Not stocked",
  restock: "Out of stock",
  price_gap: "Price gap",
};

const inr = (n: number) => `₹${Math.round(n).toLocaleString("en-IN")}`;

function Slot({ o, active, onOpen }: { o: Opportunity; active: boolean; onOpen: () => void }) {
  return (
    <li>
      <button className={`slot slot-${o.kind} ${active ? "slot-active" : ""}`} onClick={onOpen} aria-pressed={active}>
        <span className="slot-box" aria-hidden>
          <span className="slot-count">{o.unique_customers}</span>
          <span className="slot-unit">asked</span>
        </span>
        <span className="slot-label">
          <b>{o.label}</b>
          <span>
            {KIND_LABEL[o.kind]}
            {o.trend_pct != null && o.trend_pct !== 0 && (
              <em className={o.trend_pct > 0 ? "up" : "down"}> {o.trend_pct > 0 ? "▲" : "▼"} {Math.abs(Math.round(o.trend_pct))}%</em>
            )}
          </span>
        </span>
      </button>
    </li>
  );
}

function Fulfil({ o, onClose }: { o: Opportunity; onClose: () => void }) {
  const [name, setName] = useState(o.suggested_name);
  const [price, setPrice] = useState(String(o.suggested_price || ""));
  const [qty, setQty] = useState(String(o.suggested_qty || ""));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState<FulfilResult | null>(null);

  const run = async (fn: () => Promise<FulfilResult>) => {
    setBusy(true);
    setErr("");
    try {
      setDone(await fn());
      notifyChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };

  const listNew = () => run(() => api.listing({ name, price: Number(price), qty: Number(qty), category: "Grocery" }));
  const restock = () =>
    run(async () => {
      const po = await api.createPO(o.linked_sku!, Number(qty));
      return api.receivePO(po.id);
    });

  return (
    <aside className="drawer" aria-label={`Act on ${o.label}`}>
      <header>
        <div>
          <h3>{o.suggested_name || o.label}</h3>
          <p>
            {o.unique_customers} shoppers · {o.events} requests · {o.confidence} confidence
          </p>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close">×</button>
      </header>
      <p className="why">{o.action}</p>
      <p className="why muted">{o.rationale}</p>
      <dl className="facts">
        <div><dt>Revenue at risk</dt><dd>{inr(o.revenue_at_risk)}</dd></div>
        <div><dt>Est. demand</dt><dd>{o.est_weekly_units} / week</dd></div>
        <div><dt>Waiting for a message</dt><dd>{o.waitlist_count}</dd></div>
      </dl>

      {!done && o.kind === "new_listing" && (
        <form className="form" onSubmit={(e) => { e.preventDefault(); void listNew(); }}>
          <label>Product name<input value={name} onChange={(e) => setName(e.target.value)} required minLength={2} /></label>
          <div className="row2">
            <label>Price (₹)<input type="number" min="1" value={price} onChange={(e) => setPrice(e.target.value)} required /></label>
            <label>Opening stock<input type="number" min="1" value={qty} onChange={(e) => setQty(e.target.value)} required /></label>
          </div>
          <button className="btn btn-primary" disabled={busy}>{busy ? "Listing…" : `List it and message ${o.waitlist_count} waiting shoppers`}</button>
          <p className="fine">Prices and quantity are estimates from shopper requests — edit before you commit. Nothing is ordered or sent until you click.</p>
        </form>
      )}

      {!done && o.kind === "restock" && o.linked_sku && (
        <form className="form" onSubmit={(e) => { e.preventDefault(); void restock(); }}>
          <label>Order quantity<input type="number" min="1" value={qty} onChange={(e) => setQty(e.target.value)} required /></label>
          <button className="btn btn-primary" disabled={busy}>{busy ? "Working…" : "Approve order and mark received"}</button>
          <p className="fine">For the demo, receiving is one step. In production the order stays open until the delivery arrives.</p>
        </form>
      )}

      {!done && o.kind === "price_gap" && (
        <p className="why">Shoppers can find this item but not at their price. Source a cheaper variant, or run a promotion, then re-check this shelf.</p>
      )}

      {err && <p className="err" role="alert">{err}</p>}
      {done && (
        <div className="done" role="status">
          <b>Done.</b> {done.notifications.length} shopper{done.notifications.length === 1 ? "" : "s"} messaged.
          {done.notifications.slice(0, 3).map((n) => (
            <blockquote key={n.id} lang={n.language}>{n.message}</blockquote>
          ))}
          <button className="btn" onClick={onClose}>Close</button>
        </div>
      )}
    </aside>
  );
}

export default function Shelf({ items }: { items: Opportunity[] }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const open = items.find((o) => o.cluster_id === openId) ?? null;

  return (
    <section className="panel shelf-panel" aria-labelledby="shelf-h">
      <header className="panel-head">
        <div>
          <h2 id="shelf-h">The shelf</h2>
          <p>Empty slots are things shoppers asked for that you can't serve yet. Biggest demand first.</p>
        </div>
      </header>
      {items.length === 0 ? (
        <p className="empty">No repeat requests yet. Ask the assistant for something you don't stock and it will show up here.</p>
      ) : (
        <div className="shelf-wrap">
          <ul className="shelf">
            {items.map((o) => (
              <Slot key={o.cluster_id} o={o} active={o.cluster_id === openId} onOpen={() => setOpenId(o.cluster_id === openId ? null : o.cluster_id)} />
            ))}
          </ul>
          {open && <Fulfil key={open.cluster_id} o={open} onClose={() => setOpenId(null)} />}
        </div>
      )}
    </section>
  );
}
