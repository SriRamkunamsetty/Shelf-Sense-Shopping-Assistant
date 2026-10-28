import { useEffect, useState } from "react";
import { api } from "./api";
import Chat from "./components/Chat";
import Owner from "./components/Owner";

type View = "split" | "shopper" | "owner";

const SHOPPERS = [
  { id: "c001", label: "Demo shopper A" },
  { id: "c002", label: "Demo shopper B" },
  { id: "c003", label: "Demo shopper C" },
];

export default function App() {
  const wide = () => window.matchMedia("(min-width: 1180px)").matches;
  const [view, setView] = useState<View>(wide() ? "split" : "shopper");
  const [shopper, setShopper] = useState(SHOPPERS[0].id);
  const [health, setHealth] = useState<{ engine: string; model: string | null; demo_mode: boolean } | null>(null);
  const [down, setDown] = useState(false);

  useEffect(() => {
    api.health().then((h) => { setHealth(h); setDown(false); }).catch(() => setDown(true));
  }, []);

  const showChat = view !== "owner";
  const showOwner = view !== "shopper";

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <span className="mark" aria-hidden><i /><i /><i /></span>
          <div>
            <h1>ShelfSense</h1>
            <p>Hear what shoppers want. Stock it. Tell them.</p>
          </div>
        </div>
        <nav className="seg seg-lg" aria-label="View">
          {([["split", "Side by side"], ["shopper", "Shopper"], ["owner", "Owner"]] as const).map(([v, label]) => (
            <button key={v} className={view === v ? "on" : ""} onClick={() => setView(v)} aria-pressed={view === v}>{label}</button>
          ))}
        </nav>
        <div className="status" role="status">
          {down ? (
            <span className="pill pill-bad">API unreachable</span>
          ) : health ? (
            <span className="pill" title={health.model ?? "Built-in rules engine (no Gemini credentials configured)"}>
              <i className={health.engine === "gemini" ? "dot ok" : "dot"} />
              {health.engine === "gemini" ? `Gemini · ${health.model}` : "Built-in engine"}
            </span>
          ) : null}
        </div>
      </header>

      <main className={`stage stage-${view}`}>
        {showChat && (
          <div className="shopper-col">
            <label className="who">
              Chatting as
              <select value={shopper} onChange={(e) => setShopper(e.target.value)}>
                {SHOPPERS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
              </select>
            </label>
            <Chat customerId={shopper} compact={view === "split"} />
          </div>
        )}
        {showOwner && (
          <div className="owner-col">
            <Owner demo={health?.demo_mode ?? true} />
          </div>
        )}
      </main>
    </div>
  );
}
