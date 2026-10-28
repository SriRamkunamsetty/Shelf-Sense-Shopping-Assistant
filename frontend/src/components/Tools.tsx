import { useState } from "react";
import { api, notifyChanged } from "../api";
import type { Audit, Lang } from "../types";

const QUICK = ["What should I restock first?", "What are shoppers asking for that I don't have?", "Brief me for today"];

export function Copilot() {
  const [log, setLog] = useState<{ q: string; a: string; engine: string }[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  const ask = async (q: string) => {
    if (!q.trim() || busy) return;
    setBusy(true);
    setInput("");
    try {
      const r = await api.opsChat(q);
      setLog((l) => [...l, { q, a: r.reply, engine: r.engine }]);
    } catch (e) {
      setLog((l) => [...l, { q, a: e instanceof Error ? e.message : "Request failed", engine: "error" }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel" aria-labelledby="co-h">
      <header className="panel-head">
        <div>
          <h2 id="co-h">Ask your copilot</h2>
          <p>Answers come from your live data. It suggests; you approve.</p>
        </div>
      </header>
      <div className="chips">{QUICK.map((q) => <button key={q} className="chip" onClick={() => void ask(q)}>{q}</button>)}</div>
      <div className="co-log">
        {log.map((m, i) => (
          <div key={i}>
            <p className="co-q">{m.q}</p>
            <p className="co-a">{m.a}</p>
            <small>{m.engine === "gemini" ? "Gemini + ADK agents" : m.engine === "offline" ? "Built-in rules engine" : ""}</small>
          </div>
        ))}
        {busy && <p className="muted">Thinking…</p>}
      </div>
      <form className="composer" onSubmit={(e) => { e.preventDefault(); void ask(input); }}>
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask about stock, demand or forecasts" aria-label="Ask the copilot" maxLength={500} />
        <button className="btn btn-primary" disabled={busy || !input.trim()}>Ask</button>
      </form>
    </section>
  );
}

export function Simulator({ demo }: { demo: boolean }) {
  const [query, setQuery] = useState("vegan protein bar");
  const [count, setCount] = useState(8);
  const [lang, setLang] = useState<Lang>("en");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  if (!demo) return null;
  const go = async () => {
    setBusy(true);
    setMsg("");
    try {
      const r = await api.simulate(query, count, lang);
      setMsg(`${r.simulated} shoppers asked. ${Object.entries(r.outcomes).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(", ")}.`);
      notifyChanged();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel panel-demo" aria-labelledby="sim-h">
      <header className="panel-head">
        <div>
          <h2 id="sim-h">Send test shoppers</h2>
          <p>Demo only. Pushes synthetic shoppers through the same search, logging and waitlist path as real chats.</p>
        </div>
      </header>
      <form className="form" onSubmit={(e) => { e.preventDefault(); void go(); }}>
        <label>They ask for<input value={query} onChange={(e) => setQuery(e.target.value)} required maxLength={200} /></label>
        <div className="row2">
          <label>How many
            <select value={count} onChange={(e) => setCount(Number(e.target.value))}>{[3, 5, 8, 12, 20].map((n) => <option key={n}>{n}</option>)}</select>
          </label>
          <label>Language
            <select value={lang} onChange={(e) => setLang(e.target.value as Lang)}><option value="en">English</option><option value="hi">हिंदी</option><option value="te">తెలుగు</option></select>
          </label>
        </div>
        <button className="btn" disabled={busy}>{busy ? "Sending…" : "Send shoppers"}</button>
      </form>
      {msg && <p className="fine" role="status">{msg}</p>}
      <button className="link danger" onClick={() => { if (confirm("Reset all demo data?")) void api.reset().then(notifyChanged); }}>Reset demo data</button>
    </section>
  );
}

export function Activity({ items }: { items: Audit[] }) {
  return (
    <section className="panel" aria-labelledby="act-h">
      <header className="panel-head">
        <div>
          <h2 id="act-h">What changed</h2>
          <p>Every order, listing and message is logged.</p>
        </div>
      </header>
      {items.length === 0 ? (
        <p className="empty">Nothing yet. Approve an order or list a product and it will appear here.</p>
      ) : (
        <ul className="activity">
          {items.map((a) => (
            <li key={a.id}>
              <time>{new Date(a.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>
              <span><b>{a.action.replace(".", " ")}</b> {Object.entries(a.details).filter(([k]) => ["sku", "qty", "notified"].includes(k)).map(([k, v]) => `${k} ${String(v)}`).join(" · ")}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
