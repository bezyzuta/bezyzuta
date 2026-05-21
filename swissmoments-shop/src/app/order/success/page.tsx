import Link from "next/link";
import { CheckCircle2, Download, Mail } from "lucide-react";
import { stripe } from "@/lib/stripe";
import { supabaseAdmin, createSignedDownload } from "@/lib/supabase";
import { getProductBySlug } from "@/lib/products";
import { formatPriceCHF } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ClearCartOnMount } from "@/components/clear-cart-on-mount";

export const dynamic = "force-dynamic";

interface SearchParams {
  session_id?: string;
}

/**
 * Bestätigungs-Seite nach erfolgreichem Stripe-Checkout.
 *
 * Quelle der Wahrheit ist die Stripe-Session — die Order in Supabase wird
 * vom Webhook angelegt und kann beim ersten Aufruf noch fehlen (Race).
 * Wir zeigen also die Items aus dem Stripe-Line-Items-Endpoint und holen
 * Download-Links direkt aus dem Storage.
 */
export default async function OrderSuccessPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const { session_id } = await searchParams;

  if (!session_id) {
    return (
      <FallbackMessage
        title="Keine Session gefunden"
        text="Wir konnten deine Bestellung nicht laden. Schau bitte in dein E-Mail-Postfach — wir haben dir die Details geschickt."
      />
    );
  }

  let session;
  try {
    session = await stripe.checkout.sessions.retrieve(session_id, {
      expand: ["line_items"],
    });
  } catch (err) {
    console.error("[success] session fetch failed", err);
    return (
      <FallbackMessage
        title="Bestellung wird verarbeitet"
        text="Wir konnten deine Bestellung gerade nicht laden. Sie ist aber bei uns angekommen — du bekommst gleich eine Bestätigungsmail."
      />
    );
  }

  if (session.payment_status !== "paid") {
    return (
      <FallbackMessage
        title="Zahlung noch ausstehend"
        text="Stripe meldet noch keine bestätigte Zahlung. In der Regel dauert das nur wenige Sekunden — bitte lade die Seite gleich neu."
      />
    );
  }

  const supabase = supabaseAdmin();
  const lineItems = session.line_items?.data ?? [];

  // Slug aus Session-Metadaten ableiten (Format "slug:qty,slug:qty").
  const slugs = (session.metadata?.cart ?? "")
    .split(",")
    .map((s) => s.split(":")[0]?.trim())
    .filter(Boolean) as string[];

  const downloads = await Promise.all(
    slugs.map(async (slug) => {
      const product = getProductBySlug(slug);
      const { data: file } = await supabase
        .from("products_files")
        .select("storage_path")
        .eq("slug", slug)
        .maybeSingle();
      const url = file?.storage_path
        ? await createSignedDownload(file.storage_path)
        : null;
      return {
        slug,
        title: product?.title ?? slug,
        cover: product?.cover ?? "",
        url,
      };
    }),
  );

  const email = session.customer_details?.email ?? session.customer_email;

  return (
    <div className="container max-w-2xl py-16 md:py-24">
      <ClearCartOnMount />
      <div className="text-center">
        <CheckCircle2
          className="mx-auto h-14 w-14 text-brand-red"
          aria-hidden="true"
        />
        <h1 className="mt-4 font-serif text-3xl text-brand-ink md:text-4xl">
          Vielen Dank für deine Bestellung!
        </h1>
        <p className="mt-3 text-brand-ink/70">
          {email && (
            <>
              Wir haben eine Bestätigung an <strong>{email}</strong> geschickt.
              <br />
            </>
          )}
          Du kannst deine E-Books gleich hier herunterladen.
        </p>
      </div>

      <div className="mt-10 space-y-3">
        {downloads.map((d) => (
          <div
            key={d.slug}
            className="flex items-center justify-between rounded-2xl bg-white p-5 shadow-sm ring-1 ring-brand-ink/5"
          >
            <div className="min-w-0">
              <p className="font-serif text-lg text-brand-ink">{d.title}</p>
              <p className="mt-0.5 text-xs text-brand-ink/55">
                {d.url
                  ? "Link 7 Tage gültig"
                  : "Wird gleich per E-Mail nachgereicht"}
              </p>
            </div>
            {d.url ? (
              <Button asChild size="sm">
                <a href={d.url} download>
                  <Download className="h-4 w-4" />
                  PDF
                </a>
              </Button>
            ) : (
              <span className="inline-flex items-center gap-2 rounded-full bg-brand-cream-dark/60 px-3 py-1.5 text-xs text-brand-ink/60">
                <Mail className="h-3.5 w-3.5" />
                Folgt per E-Mail
              </span>
            )}
          </div>
        ))}
      </div>

      <div className="mt-10 rounded-2xl bg-brand-cream-dark/40 p-6 text-sm text-brand-ink/70">
        <p>
          <strong>Bezahlt:</strong>{" "}
          {formatPriceCHF((session.amount_total ?? 0) / 100)} ·{" "}
          <strong>Bestellnummer:</strong> {session.id.slice(-12)}
        </p>
        {lineItems.length > 0 && (
          <p className="mt-2 text-xs text-brand-ink/55">
            {lineItems.length}{" "}
            {lineItems.length === 1 ? "Artikel" : "Artikel"} ·{" "}
            {session.payment_method_types?.join(" / ")}
          </p>
        )}
      </div>

      <div className="mt-10 text-center">
        <Button asChild variant="outline">
          <Link href="/shop">Weiter stöbern</Link>
        </Button>
      </div>
    </div>
  );
}

function FallbackMessage({ title, text }: { title: string; text: string }) {
  return (
    <div className="container max-w-xl py-20 text-center">
      <h1 className="font-serif text-3xl text-brand-ink md:text-4xl">{title}</h1>
      <p className="mt-3 text-brand-ink/70">{text}</p>
      <Button asChild className="mt-7">
        <Link href="/">Zur Startseite</Link>
      </Button>
    </div>
  );
}
