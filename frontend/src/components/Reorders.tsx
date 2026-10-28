import { useState } from "react";
import { api, notifyChanged } from "../api";
import type { PurchaseOrder, Reorder } from "../types";

const inr = (n: number) => `₹${Math.round(n).toLocaleString("en-IN")}`;

export default function Reorders({
  items,
  pos,
  onPick,
  picked,
}: {
  items: Reorder[];
  pos: PurchaseOrder[];
  onPick: (sku: string) => void;
  picked: string;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const open = pos.filter((p) => p.status === "approved");

  const act = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setErr("");
    try {
      await fn();
      notifyChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="panel" aria-labelledby="reorder-h">
      <header className="panel-head">
        <div>
          <h2 id="reorder-h">Reorder now</h2>
          <p>Quantities cover each item's delivery time plus a week, with safety stock for a 95% service level.</p>
        </div>
      </header>
      {items.length === 0 ? (
        <p className="empty">Everything covers its delivery time. Nothing to reorder today.</p>
      ) : (
        <table className="tbl">
          <thead>
            <tr><th>Item</th><th>Cover</th><th className="num">Order</th><th className="num">Cost</th><th /></tr>
          </thead>
          <tbody>
            {items.map((r) => {
              const ordered = open.some((p) => p.sku === r.sku);
              const pct = r.days_of_cover == null ? 100 : Math.min(100, (r.days_of_cover / (r.lead_time_days + 7)) * 100);
              return (
                <tr key={r.sku} className={picked === r.sku ? "row-picked" : ""}>
                  <td>
                    <button className="link" onClick={() => onPick(r.sku)}>{r.name}</button>
                    <span className={`pri pri-${r.priority}`}>{r.priority}</span>
                    <details className="why-toggle">
                      <summary>Why this quantity</summary>
                      <small>{r.rationale}</small>
                    </details>
                  </td>
                  <td>
                    <div className="meter" title={`${r.days_of_cover} days of cover vs ${r.lead_time_days}-day delivery`}>
                      <i style={{ width: `${pct}%` }} className={r.priority === "critical" ? "bad" : ""} />
                      <b style={{ left: `${(r.lead_time_days / (r.lead_time_days + 7)) * 100}%` }} aria-hidden />
                    </div>
                    <small>{r.days_of_cover ?? "—"} days</small>
                  </td>
                  <td className="num">{r.reorder_qty}</td>
                  <td className="num">{inr(r.order_cost)}</td>
                  <td className="act">
                    <button className="btn btn-sm" disabled={busy === r.sku || ordered} onClick={() => void act(r.sku, () => api.createPO(r.sku, r.reorder_qty))}>
                      {ordered ? "Ordered" : "Approve order"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {err && <p className="err" role="alert">{err}</p>}
      {open.length > 0 && (
        <div className="po-list">
          <h3>On order</h3>
          <ul>
            {open.map((p) => (
              <li key={p.id}>
                <span>{p.qty} × {p.sku}</span>
                <button className="btn btn-sm" disabled={busy === p.id} onClick={() => void act(p.id, () => api.receivePO(p.id))}>Mark received</button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
