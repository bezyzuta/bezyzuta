import { supabaseAdmin } from "@/lib/supabase";
import { formatPriceCHF } from "@/lib/utils";
import { ResendEmailButton } from "@/components/admin/resend-email-button";

export const dynamic = "force-dynamic";

interface OrderWithItems {
  id: string;
  customer_email: string;
  customer_name: string | null;
  amount_total: number;
  status: string;
  created_at: string;
  order_items: {
    product_title: string;
    quantity: number;
    unit_price: number;
  }[];
}

export default async function AdminOrdersPage() {
  const supabase = supabaseAdmin();

  const { data, error } = await supabase
    .from("orders")
    .select(
      "id, customer_email, customer_name, amount_total, status, created_at, order_items (product_title, quantity, unit_price)",
    )
    .order("created_at", { ascending: false })
    .limit(100);

  const orders = (data ?? []) as OrderWithItems[];

  return (
    <div>
      <h1 className="font-serif text-3xl text-brand-ink">Bestellungen</h1>
      <p className="mt-1 text-sm text-brand-ink/60">
        Letzte 100 Bestellungen, neueste zuerst.
      </p>

      {error && (
        <div className="mt-6 rounded-lg bg-brand-red/10 p-4 text-sm text-brand-red">
          Fehler beim Laden: {error.message}
        </div>
      )}

      <div className="mt-8 space-y-3">
        {orders.length === 0 && !error && (
          <div className="rounded-2xl bg-white p-8 text-center text-sm text-brand-ink/60 ring-1 ring-brand-ink/5">
            Noch keine Bestellungen.
          </div>
        )}

        {orders.map((o) => (
          <div
            key={o.id}
            className="rounded-2xl bg-white p-5 ring-1 ring-brand-ink/5"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-medium text-brand-ink">{o.customer_email}</p>
                <p className="text-xs text-brand-ink/55">
                  {o.customer_name ?? "—"} ·{" "}
                  {new Date(o.created_at).toLocaleString("de-CH", {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}{" "}
                  · #{o.id.slice(0, 8)}
                </p>
              </div>
              <div className="text-right">
                <p className="font-serif text-lg text-brand-red">
                  {formatPriceCHF(o.amount_total / 100)}
                </p>
                <p className="text-xs uppercase tracking-wider text-brand-ink/50">
                  {o.status}
                </p>
              </div>
            </div>

            <ul className="mt-3 divide-y divide-brand-ink/5 text-sm">
              {o.order_items.map((it, i) => (
                <li
                  key={i}
                  className="flex items-center justify-between py-2 text-brand-ink/80"
                >
                  <span>
                    {it.quantity}× {it.product_title}
                  </span>
                  <span className="text-brand-ink/60">
                    {formatPriceCHF((it.unit_price * it.quantity) / 100)}
                  </span>
                </li>
              ))}
            </ul>

            <div className="mt-3 flex justify-end">
              <ResendEmailButton orderId={o.id} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
