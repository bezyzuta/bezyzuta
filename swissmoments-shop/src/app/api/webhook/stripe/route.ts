import { headers } from "next/headers";
import { NextResponse } from "next/server";
import type Stripe from "stripe";
import { stripe } from "@/lib/stripe";
import { supabaseAdmin, createSignedDownload } from "@/lib/supabase";
import { sendOrderConfirmation } from "@/lib/email";
import { getProductBySlug } from "@/lib/products";

export const runtime = "nodejs";
// Wir brauchen den rohen Body, damit Stripe die Signatur prüfen kann.
export const dynamic = "force-dynamic";

/**
 * POST /api/webhook/stripe
 *
 * 1. Signatur verifizieren (verhindert dass jemand uns Fake-Orders unterjubelt).
 * 2. Bei `checkout.session.completed`:
 *    - Order + order_items in Supabase anlegen
 *    - Pro Produkt eine signierte Download-URL holen
 *    - Bestätigungsmail mit Links versenden
 */
export async function POST(req: Request) {
  const sig = (await headers()).get("stripe-signature");
  const secret = process.env.STRIPE_WEBHOOK_SECRET;
  if (!sig || !secret) {
    return NextResponse.json({ error: "Missing signature" }, { status: 400 });
  }

  const rawBody = await req.text();

  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(rawBody, sig, secret);
  } catch (err) {
    console.error("[webhook] signature verification failed", err);
    return NextResponse.json({ error: "Bad signature" }, { status: 400 });
  }

  if (event.type !== "checkout.session.completed") {
    return NextResponse.json({ received: true });
  }

  const session = event.data.object as Stripe.Checkout.Session;

  try {
    await fulfillOrder(session);
    return NextResponse.json({ received: true });
  } catch (err) {
    console.error("[webhook] fulfillment failed", err);
    // 500 → Stripe versucht es erneut. Idempotenz wird via
    // ON CONFLICT (stripe_session_id) sichergestellt.
    return NextResponse.json({ error: "Fulfillment failed" }, { status: 500 });
  }
}

async function fulfillOrder(session: Stripe.Checkout.Session) {
  const supabase = supabaseAdmin();
  const sessionId = session.id;
  const customerEmail = session.customer_details?.email ?? session.customer_email;
  if (!customerEmail) throw new Error("Keine Customer-Email in Session");

  // Idempotenz — wenn die Order schon existiert, brechen wir früh ab.
  const { data: existing } = await supabase
    .from("orders")
    .select("id")
    .eq("stripe_session_id", sessionId)
    .maybeSingle();
  if (existing) return;

  // Cart aus Metadaten parsen (Format: "slug1:2,slug2:1").
  const cartMeta = session.metadata?.cart ?? "";
  const cartEntries = cartMeta
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((entry) => {
      const [slug, qtyStr] = entry.split(":");
      return { slug, quantity: Math.max(1, parseInt(qtyStr ?? "1", 10)) };
    });

  if (cartEntries.length === 0) throw new Error("Cart-Metadaten leer");

  // Order anlegen.
  const { data: order, error: orderErr } = await supabase
    .from("orders")
    .insert({
      stripe_session_id: sessionId,
      customer_email: customerEmail,
      customer_name: session.customer_details?.name ?? null,
      amount_total: session.amount_total ?? 0,
      currency: session.currency ?? "chf",
      status: "paid",
    })
    .select("id")
    .single();
  if (orderErr || !order) throw orderErr ?? new Error("Order-Insert failed");

  // Order Items anlegen + Download-Links sammeln.
  const itemRows: Array<{
    order_id: string;
    product_slug: string;
    product_title: string;
    unit_price: number;
    quantity: number;
  }> = [];
  const emailItems: Array<{
    title: string;
    quantity: number;
    unitPriceChf: number;
    downloadUrl: string | null;
  }> = [];

  for (const entry of cartEntries) {
    const product = getProductBySlug(entry.slug);
    if (!product) {
      console.warn(`[webhook] Unbekannter Slug in Order: ${entry.slug}`);
      continue;
    }

    itemRows.push({
      order_id: order.id,
      product_slug: product.slug,
      product_title: product.title,
      unit_price: Math.round(product.price * 100),
      quantity: entry.quantity,
    });

    // Storage-Pfad aus DB lesen (vom Admin-Upload gesetzt).
    const { data: file } = await supabase
      .from("products_files")
      .select("storage_path")
      .eq("slug", product.slug)
      .maybeSingle();

    const downloadUrl = file?.storage_path
      ? await createSignedDownload(file.storage_path)
      : null;

    emailItems.push({
      title: product.title,
      quantity: entry.quantity,
      unitPriceChf: product.price,
      downloadUrl,
    });
  }

  if (itemRows.length > 0) {
    const { error: itemsErr } = await supabase
      .from("order_items")
      .insert(itemRows);
    if (itemsErr) throw itemsErr;
  }

  // Email — wir loggen Fehler aber lassen den Webhook trotzdem erfolgreich
  // antworten (sonst retried Stripe und der Kunde bekommt 5 Mails).
  // Email-Resend ist über /admin/orders manuell möglich.
  try {
    await sendOrderConfirmation({
      to: customerEmail,
      customerName: session.customer_details?.name ?? null,
      orderId: order.id,
      totalChf: (session.amount_total ?? 0) / 100,
      items: emailItems,
    });
  } catch (err) {
    console.error("[webhook] email send failed (order ist trotzdem gespeichert)", err);
  }
}
