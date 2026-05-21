import Link from "next/link";
import { supabaseAdmin } from "@/lib/supabase";
import { formatPriceCHF } from "@/lib/utils";
import { products } from "@/lib/products";

export const dynamic = "force-dynamic";

export default async function AdminDashboardPage() {
  const supabase = supabaseAdmin();

  const [{ data: recentOrders }, { data: stats }, { data: filesData }] = await Promise.all([
    supabase
      .from("orders")
      .select("id, customer_email, amount_total, created_at")
      .order("created_at", { ascending: false })
      .limit(5),
    supabase.from("orders").select("amount_total"),
    supabase.from("products_files").select("slug"),
  ]);

  const totalRevenue =
    (stats ?? []).reduce((sum, o) => sum + (o.amount_total ?? 0), 0) / 100;
  const totalOrders = stats?.length ?? 0;
  const uploadedSlugs = new Set((filesData ?? []).map((f) => f.slug));
  const missingPdfs = products.filter((p) => !uploadedSlugs.has(p.slug));

  return (
    <div className="space-y-10">
      <div>
        <h1 className="font-serif text-3xl text-brand-ink">Dashboard</h1>
        <p className="mt-1 text-sm text-brand-ink/60">
          Schneller Überblick über deinen Shop.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Bestellungen" value={String(totalOrders)} />
        <StatCard label="Umsatz total" value={formatPriceCHF(totalRevenue)} />
        <StatCard
          label="PDFs hochgeladen"
          value={`${uploadedSlugs.size} / ${products.length}`}
          warn={missingPdfs.length > 0}
        />
      </div>

      {missingPdfs.length > 0 && (
        <div className="rounded-2xl border border-brand-gold/40 bg-brand-gold/10 p-5 text-sm text-brand-ink">
          <p className="font-medium">
            Für {missingPdfs.length}{" "}
            {missingPdfs.length === 1 ? "Produkt" : "Produkte"} fehlt noch die
            PDF-Datei:
          </p>
          <ul className="mt-2 list-disc pl-5 text-brand-ink/80">
            {missingPdfs.map((p) => (
              <li key={p.slug}>{p.title}</li>
            ))}
          </ul>
          <Link
            href="/admin/products"
            className="mt-3 inline-block font-medium text-brand-red hover:underline"
          >
            Jetzt hochladen →
          </Link>
        </div>
      )}

      <section>
        <div className="flex items-baseline justify-between">
          <h2 className="font-serif text-xl text-brand-ink">
            Letzte Bestellungen
          </h2>
          <Link
            href="/admin/orders"
            className="text-sm text-brand-red hover:underline"
          >
            Alle anzeigen
          </Link>
        </div>
        <div className="mt-4 overflow-hidden rounded-2xl bg-white ring-1 ring-brand-ink/5">
          {recentOrders && recentOrders.length > 0 ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-brand-ink/10 bg-brand-cream-dark/30 text-left text-xs uppercase tracking-wider text-brand-ink/60">
                  <th className="px-5 py-3">Datum</th>
                  <th className="px-5 py-3">E-Mail</th>
                  <th className="px-5 py-3 text-right">Betrag</th>
                </tr>
              </thead>
              <tbody>
                {recentOrders.map((o) => (
                  <tr key={o.id} className="border-b border-brand-ink/5">
                    <td className="px-5 py-3 text-brand-ink/70">
                      {new Date(o.created_at).toLocaleString("de-CH", {
                        dateStyle: "short",
                        timeStyle: "short",
                      })}
                    </td>
                    <td className="px-5 py-3 text-brand-ink">
                      {o.customer_email}
                    </td>
                    <td className="px-5 py-3 text-right font-medium text-brand-ink">
                      {formatPriceCHF((o.amount_total ?? 0) / 100)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="p-6 text-sm text-brand-ink/60">
              Noch keine Bestellungen.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

function StatCard({
  label,
  value,
  warn,
}: {
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div
      className={`rounded-2xl bg-white p-5 ring-1 ${
        warn ? "ring-brand-gold/40" : "ring-brand-ink/5"
      }`}
    >
      <p className="text-xs uppercase tracking-wider text-brand-ink/55">
        {label}
      </p>
      <p className="mt-2 font-serif text-3xl text-brand-ink">{value}</p>
    </div>
  );
}
