import { useEffect, useState } from "react";
import { api } from "../api";
import type { Forecast } from "../types";

const W = 640;
const H = 220;
const PAD = { l: 34, r: 10, t: 12, b: 24 };

export default function ForecastChart({ sku, names }: { sku: string; names: Record<string, string> }) {
  const [f, setF] = useState<Forecast | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    let alive = true;
    setF(null);
    setErr("");
    api.forecast(sku).then((r) => alive && setF(r)).catch((e: Error) => alive && setErr(e.message));
    return () => {
      alive = false;
    };
  }, [sku]);

  if (err) return <p className="err">Couldn't load the forecast: {err}</p>;
  if (!f) return <p className="empty">Loading forecast…</p>;

  const hist = f.history;
  const all = [...hist.map((h) => h.corrected), ...hist.map((h) => h.units), ...f.forecast.map((p) => p.hi)];
  const max = Math.max(1, ...all) * 1.08;
  const n = hist.length + f.forecast.length;
  const x = (i: number) => PAD.l + (i / (n - 1)) * (W - PAD.l - PAD.r);
  const y = (v: number) => PAD.t + (1 - v / max) * (H - PAD.t - PAD.b);
  const line = (vals: number[], off = 0) => vals.map((v, i) => `${i === 0 ? "M" : "L"}${x(i + off).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const off = hist.length;
  const band =
    f.forecast.map((p, i) => `${i === 0 ? "M" : "L"}${x(i + off).toFixed(1)},${y(p.hi).toFixed(1)}`).join(" ") +
    [...f.forecast].reverse().map((p, i) => `L${x(f.forecast.length - 1 - i + off).toFixed(1)},${y(p.lo).toFixed(1)}`).join(" ") + "Z";
  const better = f.wape_model != null && f.wape_seasonal_naive ? Math.round((1 - f.wape_model / f.wape_seasonal_naive) * 100) : null;
  const ticks = [0, 0.5, 1].map((t) => Math.round(max * t));

  return (
    <figure className="forecast">
      <figcaption>
        <b>{names[sku] ?? f.name}</b>
        <span>~{f.daily_mean.toFixed(1)} units/day expected</span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Daily unit sales for ${f.name}: last ${hist.length} days and a ${f.forecast.length}-day forecast`}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} className="grid" />
            <text x={PAD.l - 6} y={y(t) + 4} textAnchor="end" className="axis">{t}</text>
          </g>
        ))}
        <rect x={x(off - 0.5)} y={PAD.t} width={W - PAD.r - x(off - 0.5)} height={H - PAD.t - PAD.b} className="future" />
        <path d={band} className="band" />
        {hist.map((h, i) =>
          !h.in_stock ? <rect key={h.date} x={x(i) - 3} y={PAD.t} width={6} height={H - PAD.t - PAD.b} className="stockout"><title>{h.date}: out of stock</title></rect> : null,
        )}
        <path d={line(hist.map((h) => h.units))} className="recorded" />
        <path d={line(hist.map((h) => h.corrected))} className="corrected" />
        <path d={line(f.forecast.map((p) => p.mean), off)} className="fc" />
        <text x={x(off) + 6} y={PAD.t + 12} className="axis">forecast</text>
        <text x={PAD.l} y={H - 6} className="axis">{hist[0]?.date.slice(5)}</text>
        <text x={W - PAD.r} y={H - 6} textAnchor="end" className="axis">{f.forecast[f.forecast.length - 1]?.date.slice(5)}</text>
      </svg>
      <ul className="legend">
        <li><i className="lg recorded" />Recorded sales</li>
        <li><i className="lg corrected" />Corrected for stock-outs{f.lost_units_estimate > 0 ? ` (+${Math.round(f.lost_units_estimate)} lost units)` : ""}</li>
        <li><i className="lg stockout" />Shelf was empty</li>
      </ul>
      <p className="fine">
        {f.method}.{" "}
        {f.signal_uplift_per_day > 0 && <>Includes +{f.signal_uplift_per_day.toFixed(1)}/day from shoppers turned away. </>}
        {f.wape_model != null && (
          <>Backtest error {Math.round(f.wape_model * 100)}% vs {Math.round((f.wape_seasonal_naive ?? 0) * 100)}% for last-week-repeats{better != null && better > 0 ? ` (${better}% lower)` : ""}.</>
        )}
      </p>
    </figure>
  );
}
