export type Lang = "en" | "hi" | "te";
export type Outcome = "in_stock" | "out_of_stock" | "over_budget" | "partial" | "not_carried";

export interface Match {
  sku: string;
  name: string;
  price: number;
  stock: number;
  category: string;
  coverage: number;
  in_stock: boolean;
}

export interface TraceStep {
  agent: string;
  action: string;
  detail: string;
}

export interface ChatReply {
  reply: string;
  language: Lang;
  outcome: Outcome | null;
  products: Match[];
  substitutes: Match[];
  offer: { need: string } | null;
  waitlisted: boolean;
  trace: TraceStep[];
  engine: "offline" | "gemini" | "offline-fallback";
  session_id: string;
}

export interface Notice {
  id: string;
  customer_id: string;
  sku: string;
  product_name: string;
  message: string;
  language: Lang;
  created_at: string;
  read: boolean;
}

export interface Summary {
  window_days: number;
  queries: number;
  fulfilled: number;
  unmet: number;
  fulfilment_rate: number | null;
  unmet_shoppers: number;
  open_needs: number;
  revenue_at_risk: number;
  waitlist_open: number;
  waitlist_recovered: number;
  critical_reorders: number;
  low_stock_skus: number;
  catalog_size: number;
}

export interface Opportunity {
  cluster_id: string;
  kind: "new_listing" | "restock" | "price_gap";
  label: string;
  unique_customers: number;
  events: number;
  trend_pct: number | null;
  confidence: "low" | "medium" | "high";
  est_weekly_units: number;
  suggested_name: string;
  suggested_price: number;
  suggested_qty: number;
  revenue_at_risk: number;
  linked_sku: string | null;
  nearest_skus: string[];
  waitlist_count: number;
  action: string;
  rationale: string;
}

export interface Reorder {
  sku: string;
  name: string;
  stock: number;
  on_order: number;
  lead_time_days: number;
  days_of_cover: number | null;
  forecast_next_7d: number;
  safety_stock: number;
  reorder_qty: number;
  unit_cost: number;
  order_cost: number;
  revenue_protected: number;
  priority: "critical" | "high" | "normal";
  rationale: string;
}

export interface Plan {
  reorders: Reorder[];
  opportunities: Opportunity[];
  total_order_cost: number;
  total_revenue_at_risk: number;
}

export interface PurchaseOrder {
  id: string;
  sku: string;
  qty: number;
  status: string;
  unit_cost: number;
  created_at: string;
}

export interface Forecast {
  sku: string;
  name: string;
  method: string;
  history: { date: string; units: number; corrected: number; in_stock: boolean }[];
  forecast: { date: string; mean: number; lo: number; hi: number }[];
  daily_mean: number;
  lost_units_estimate: number;
  signal_uplift_per_day: number;
  wape_model: number | null;
  wape_seasonal_naive: number | null;
  wape_moving_avg: number | null;
}

export interface InventoryItem {
  sku: string;
  name: string;
  stock: number;
  on_order: number;
  price: number;
}

export interface Audit {
  id: string;
  ts: string;
  actor: string;
  action: string;
  details: Record<string, unknown>;
}

export interface FulfilResult {
  notifications: Notice[];
  product?: { sku: string; name: string; stock: number };
}
