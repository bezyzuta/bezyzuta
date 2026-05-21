import { NextResponse } from "next/server";
import { stripe, chfToRappen } from "@/lib/stripe";
import { getProductBySlug } from "@/lib/products";

export const runtime = "nodejs";

interface CheckoutRequestItem {
  slug: string;
  quantity: number;
}

/**
 * POST /api/checkout
 *
 * Body: { items: [{ slug, quantity }] }
 *
 * Validiert die Produkte gegen den File-Katalog (Server-side, damit der
 * Client den Preis nicht manipulieren kann), erstellt eine Stripe-Checkout-
 * Session und gibt die `url` zurück.
 */
export async function POST(req: Request) {
  try {
    const body = (await req.json()) as { items?: CheckoutRequestItem[] };
    const items = body.items ?? [];

    if (items.length === 0) {
      return NextResponse.json({ error: "Cart leer" }, { status: 400 });
    }

    // Server-side Validierung: jeden Slug gegen den Katalog matchen.
    const validated = items.map((req) => {
      const p = getProductBySlug(req.slug);
      if (!p) throw new Error(`Unbekanntes Produkt: ${req.slug}`);
      const qty = Math.max(1, Math.min(10, Math.floor(req.quantity)));
      return { product: p, quantity: qty };
    });

    const siteUrl =
      process.env.NEXT_PUBLIC_SITE_URL?.replace(/\/$/, "") ??
      new URL(req.url).origin;

    const session = await stripe.checkout.sessions.create({
      mode: "payment",
      payment_method_types: ["card", "twint"],
      line_items: validated.map(({ product, quantity }) => ({
        quantity,
        price_data: {
          currency: "chf",
          unit_amount: chfToRappen(product.price),
          product_data: {
            name: product.title,
            description: product.subtitle,
            images: [absoluteCoverUrl(product.cover, siteUrl)],
            metadata: { slug: product.slug },
          },
        },
      })),
      // Slug-Liste in Metadaten — der Webhook braucht das, weil
      // Stripe price_data.product_data.metadata nicht 1:1 zurückgibt.
      metadata: {
        cart: validated
          .map(({ product, quantity }) => `${product.slug}:${quantity}`)
          .join(","),
      },
      success_url: `${siteUrl}/order/success?session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${siteUrl}/order/cancel`,
      automatic_tax: { enabled: false },
      billing_address_collection: "auto",
      // E-Mail-Sammlung — kritisch, da wir den Download-Link dorthin schicken.
      customer_creation: "if_required",
      locale: "de",
      // Wir verkaufen digitale Güter — keine Versandadresse.
    });

    return NextResponse.json({ url: session.url });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unbekannter Fehler";
    console.error("[checkout]", err);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}

/**
 * Stripe akzeptiert nur absolute https-URLs für Produktbilder.
 * Bei relativen Pfaden (z.B. /covers/foo.jpg) bauen wir die volle URL.
 */
function absoluteCoverUrl(cover: string, siteUrl: string): string {
  if (cover.startsWith("http://") || cover.startsWith("https://")) return cover;
  return `${siteUrl}${cover.startsWith("/") ? "" : "/"}${cover}`;
}
