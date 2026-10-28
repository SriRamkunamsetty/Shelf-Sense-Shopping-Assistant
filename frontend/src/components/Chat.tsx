import { useCallback, useEffect, useRef, useState } from "react";
import { api, notifyChanged } from "../api";
import type { ChatReply, Lang, Match, Notice, TraceStep } from "../types";

interface Msg {
  id: number;
  role: "user" | "bot" | "notice";
  text: string;
  products?: Match[];
  substitutes?: Match[];
  offer?: { need: string } | null;
  trace?: TraceStep[];
  engine?: ChatReply["engine"];
  answered?: boolean;
}

type LangChoice = Lang | "auto";

const SPEECH_LANG: Record<LangChoice, string> = { auto: "en-IN", en: "en-IN", hi: "hi-IN", te: "te-IN" };
const YES: Record<Lang, [string, string]> = {
  en: ["Yes, notify me", "No thanks"],
  hi: ["हाँ, बताइए", "नहीं"],
  te: ["అవును, చెప్పండి", "వద్దు"],
};
const YES_TEXT: Record<Lang, [string, string]> = { en: ["yes", "no thanks"], hi: ["haan", "nahi"], te: ["avunu", "vaddu"] };
const SUGGESTIONS = [
  "gluten free pasta under 300",
  "wireless earbuds under 1000",
  "मुझे चीनी चाहिए",
  "basmati rice 5kg",
  "నాకు నూనె కావాలి",
];
const GREETING =
  "Hi! I'm the store's shopping assistant. Ask for anything — in English, हिंदी or తెలుగు. Add a budget if you like.";

const speechCtor = () =>
  (window as unknown as { SpeechRecognition?: new () => SR; webkitSpeechRecognition?: new () => SR }).SpeechRecognition ??
  (window as unknown as { webkitSpeechRecognition?: new () => SR }).webkitSpeechRecognition;

interface SR {
  lang: string;
  interimResults: boolean;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start(): void;
  stop(): void;
}

function Product({ m, dim }: { m: Match; dim?: boolean }) {
  return (
    <li className={`prod ${dim ? "prod-dim" : ""}`}>
      <span className="prod-name">{m.name}</span>
      <span className="prod-meta">
        ₹{m.price.toFixed(0)} · {m.in_stock ? (m.stock <= 5 ? `only ${m.stock} left` : "in stock") : "out of stock"}
      </span>
    </li>
  );
}

export default function Chat({ customerId, compact }: { customerId: string; compact?: boolean }) {
  const [msgs, setMsgs] = useState<Msg[]>([{ id: 0, role: "bot", text: GREETING }]);
  const [input, setInput] = useState("");
  const [lang, setLang] = useState<LangChoice>("auto");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [speak, setSpeak] = useState(false);
  const [unread, setUnread] = useState(0);
  const sessionId = useRef(`web-${Math.random().toString(36).slice(2, 10)}`);
  const nextId = useRef(1);
  const seen = useRef(new Set<string>());
  const endRef = useRef<HTMLDivElement>(null);
  const recRef = useRef<SR | null>(null);
  const canListen = !!speechCtor();

  const push = useCallback((m: Omit<Msg, "id">) => setMsgs((prev) => [...prev, { ...m, id: nextId.current++ }]), []);

  useEffect(() => endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" }), [msgs, busy]);

  // New shopper session whenever the demo customer changes.
  useEffect(() => {
    sessionId.current = `web-${Math.random().toString(36).slice(2, 10)}`;
    seen.current = new Set();
    setMsgs([{ id: nextId.current++, role: "bot", text: GREETING }]);
    setUnread(0);
  }, [customerId]);

  // Poll the shopper's inbox: this is where "we got it in" messages land.
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const { notifications } = await api.inbox(customerId);
        const fresh = notifications.filter((n: Notice) => !n.read && !seen.current.has(n.id)).reverse();
        if (!alive || !fresh.length) return;
        fresh.forEach((n) => {
          seen.current.add(n.id);
          push({ role: "notice", text: n.message });
        });
        setUnread((u) => u + fresh.length);
        void api.markRead(customerId);
      } catch {
        /* inbox is best-effort */
      }
    };
    void tick();
    const t = window.setInterval(tick, 3500);
    window.addEventListener("shelfsense:changed", tick);
    return () => {
      alive = false;
      window.clearInterval(t);
      window.removeEventListener("shelfsense:changed", tick);
    };
  }, [customerId, push]);

  const say = (text: string, l: Lang) => {
    if (!speak || !("speechSynthesis" in window)) return;
    const u = new SpeechSynthesisUtterance(text);
    u.lang = SPEECH_LANG[l];
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  };

  const send = async (text: string, opts: { hidden?: boolean } = {}) => {
    const t = text.trim();
    if (!t || busy) return;
    setInput("");
    setUnread(0);
    if (!opts.hidden) push({ role: "user", text: t });
    setBusy(true);
    try {
      const r = await api.chat(t, customerId, sessionId.current, lang);
      push({
        role: "bot",
        text: r.reply,
        products: r.products,
        substitutes: r.substitutes,
        offer: r.offer,
        trace: r.trace,
        engine: r.engine,
      });
      say(r.reply, r.language);
      notifyChanged();
    } catch (e) {
      push({ role: "bot", text: e instanceof Error ? `Couldn't reach the store assistant: ${e.message}. Try again in a moment.` : "Something went wrong." });
    } finally {
      setBusy(false);
    }
  };

  const answerOffer = (id: number, yes: boolean, l: Lang) => {
    setMsgs((prev) => prev.map((m) => (m.id === id ? { ...m, answered: true } : m)));
    void send(YES_TEXT[l][yes ? 0 : 1], { hidden: false });
  };

  const toggleMic = () => {
    const Ctor = speechCtor();
    if (!Ctor) return;
    if (listening) {
      recRef.current?.stop();
      return;
    }
    const rec = new Ctor();
    rec.lang = SPEECH_LANG[lang];
    rec.interimResults = false;
    rec.onresult = (e) => {
      const said = e.results[0]?.[0]?.transcript ?? "";
      if (said) void send(said);
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    setListening(true);
    rec.start();
  };

  const lastBot = [...msgs].reverse().find((m) => m.role === "bot" && m.offer);

  return (
    <section className={`chat ${compact ? "chat-compact" : ""}`} aria-label="Shopper assistant">
      <header className="chat-head">
        <div>
          <h2>Ask the store</h2>
          <p>Voice or text · English, हिंदी, తెలుగు</p>
        </div>
        <div className="seg" role="group" aria-label="Reply language">
          {(["auto", "en", "hi", "te"] as const).map((l) => (
            <button key={l} className={lang === l ? "on" : ""} onClick={() => setLang(l)} aria-pressed={lang === l}>
              {l === "auto" ? "Auto" : l === "en" ? "EN" : l === "hi" ? "हि" : "తె"}
            </button>
          ))}
        </div>
      </header>

      <div className="chat-log" role="log" aria-live="polite">
        {msgs.map((m) => (
          <div key={m.id} className={`msg msg-${m.role}`}>
            {m.role === "notice" && <span className="notice-tag">Back in stock</span>}
            <p lang={undefined}>{m.text}</p>
            {m.products && m.products.length > 0 && (
              <ul className="prods">{m.products.map((p) => <Product key={p.sku} m={p} />)}</ul>
            )}
            {m.substitutes && m.substitutes.length > 0 && (
              <>
                <p className="sub-label">Closest we have</p>
                <ul className="prods">{m.substitutes.map((p) => <Product key={p.sku} m={p} dim />)}</ul>
              </>
            )}
            {m.offer && !m.answered && lastBot?.id === m.id && (
              <div className="offer">
                {(() => {
                  const l = (/[ఀ-౿]/.test(m.text) ? "te" : /[ऀ-ॿ]/.test(m.text) ? "hi" : "en") as Lang;
                  return (
                    <>
                      <button className="btn btn-primary" onClick={() => answerOffer(m.id, true, l)}>{YES[l][0]}</button>
                      <button className="btn" onClick={() => answerOffer(m.id, false, l)}>{YES[l][1]}</button>
                    </>
                  );
                })()}
              </div>
            )}
            {m.trace && m.trace.length > 0 && (
              <details className="trace">
                <summary>How the agents handled this{m.engine === "gemini" ? " (Gemini)" : m.engine === "offline-fallback" ? " (fallback)" : ""}</summary>
                <ol>
                  {m.trace.map((t, i) => (
                    <li key={i}>
                      <b>{t.agent}</b> {t.action} <span>{t.detail}</span>
                    </li>
                  ))}
                </ol>
              </details>
            )}
          </div>
        ))}
        {busy && <div className="msg msg-bot typing" aria-label="Assistant is typing"><i /><i /><i /></div>}
        <div ref={endRef} />
      </div>

      {msgs.length <= 2 && (
        <div className="chips">
          {SUGGESTIONS.map((s) => (
            <button key={s} className="chip" onClick={() => void send(s)}>{s}</button>
          ))}
        </div>
      )}

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
      >
        {canListen && (
          <button type="button" className={`icon-btn ${listening ? "rec" : ""}`} onClick={toggleMic} aria-label={listening ? "Stop listening" : "Speak your request"}>
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden><path fill="currentColor" d="M12 15a3 3 0 0 0 3-3V6a3 3 0 1 0-6 0v6a3 3 0 0 0 3 3Zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V22h2v-3.08A7 7 0 0 0 19 12h-2Z" /></svg>
          </button>
        )}
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="What are you looking for?" maxLength={400} aria-label="Message" />
        <button type="button" className={`icon-btn ${speak ? "on" : ""}`} onClick={() => setSpeak((s) => !s)} aria-pressed={speak} aria-label="Read replies aloud">
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden><path fill="currentColor" d="M3 10v4h4l5 4V6L7 10H3Zm13.5 2a4.5 4.5 0 0 0-2.5-4.03v8.05A4.5 4.5 0 0 0 16.5 12Z" /></svg>
        </button>
        <button className="btn btn-primary" disabled={busy || !input.trim()}>Send</button>
      </form>
      {unread > 0 && <span className="sr-only">{unread} new notifications</span>}
    </section>
  );
}
