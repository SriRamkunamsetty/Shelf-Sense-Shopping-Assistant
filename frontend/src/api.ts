import type {
  Audit,
  ChatReply,
  Forecast,
  FulfilResult,
  InventoryItem,
  Lang,
  Notice,
  Plan,
  PurchaseOrder,
  Summary,
} from "./types";

const KEY = "shelfsense.opsKey";
export const getOpsKey = () => localStorage.getItem(KEY) ?? "";
export const setOpsKey = (v: string) => localStorage.setItem(KEY, v);

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const key = getOpsKey();
  if (key) headers["X-API-Key"] = key;
  const res = await fetch(`/api${path}`, { ...init, headers: { ...headers, ...(init.headers as object) } });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  req<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

/** Tell every live panel that data changed (shopper asked, owner acted, traffic simulated). */
export const notifyChanged = () => window.dispatchEvent(new Event("shelfsense:changed"));

export const api = {
  health: () => req<{ engine: string; model: string | null; products: number; demo_mode: boolean }>("/health"),
  chat: (message: string, customerId: string, sessionId: string, language: Lang | "auto") =>
    post<ChatReply>("/chat", { message, customer_id: customerId, session_id: sessionId, language }),
  inbox: (id: string) => req<{ notifications: Notice[] }>(`/customers/${id}/notifications`),
  markRead: (id: string) => post<{ ok: boolean }>(`/customers/${id}/notifications/read`),
  summary: () => req<Summary>("/insights/summary"),
  plan: () => req<Plan>("/restock/plan"),
  forecast: (sku: string) => req<Forecast>(`/forecast/${encodeURIComponent(sku)}?horizon=14`),
  evaluation: () =>
    req<{ model: number; seasonal_naive: number; moving_avg: number; skus: number; improvement_vs_seasonal_naive_pct: number }>(
      "/forecast/evaluation",
    ),
  inventory: () => req<{ items: InventoryItem[] }>("/inventory"),
  pos: () => req<{ purchase_orders: PurchaseOrder[] }>("/purchase-orders"),
  createPO: (sku: string, qty: number) => post<PurchaseOrder>("/purchase-orders", { sku, qty }),
  receivePO: (id: string) => post<FulfilResult>(`/purchase-orders/${id}/receive`),
  listing: (b: { name: string; price: number; qty: number; category: string }) => post<FulfilResult>("/listings", b),
  audit: () => req<{ audit: Audit[] }>("/audit?limit=12"),
  opsChat: (message: string) => post<{ reply: string; engine: string }>("/ops/chat", { message }),
  simulate: (query: string, count: number, language: Lang) =>
    post<{ simulated: number; outcomes: Record<string, number> }>("/demo/simulate", { query, count, language }),
  reset: () => post<{ ok: boolean }>("/demo/reset"),
};
