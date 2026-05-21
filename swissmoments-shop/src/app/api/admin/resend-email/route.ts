import { NextResponse } from "next/server";
import { isAdmin } from "@/lib/admin-auth";
import { supabaseAdmin, createSignedDownload } from "@/lib/supabase";
import { sendOrderConfirmation } from "@/lib/email";

export const runtime = "nodejs";

/**
 * POST /api/admin/resend-email
 *
 * Body: { orderId: string }
 *
 * Lädt eine bestehende Order + items aus DB, generiert frische
 * Download-Links und schickt die Bestätigungsmail nochmal.
 * Praktisch wenn:
 *  - Der Kunde sagt "ich hab nichts bekommen"
 *  - Das PDF erst nach dem Kauf hochgeladen wurde
 *  - Die 7-Tage-Frist abgelaufen ist
 */
export async function POST(req: Request) {
  if (!(await isAdmin())) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const { orderId } = (await req.json()) as { orderId?: string };
  if (!orderId) {
    return NextResponse.json({ error: "orderId fehlt" }, { status: 400 });
  }

  const supabase = supabaseAdmin();

  const { data: order, error: orderErr } = await supabase
    .from("orders")
    .select("id, customer_email, customer_name, amount_total")
    .eq("id", orderId)
    .single();
  if (orderErr || !order) {
    return NextResponse.json({ error: "Order nicht gefunden" }, { status: 404 });
  }

  const { data: items, error: itemsErr } = await supabase
    .from("order_items")
    .select("product_slug, product_title, unit_price, quantity")
    .eq("order_id", orderId);
  if (itemsErr) {
    return NextResponse.json({ error: itemsErr.message }, { status: 500 });
  }

  const emailItems = await Promise.all(
    (items ?? []).map(async (it) => {
      const { data: file } = await supabase
        .from("products_files")
        .select("storage_path")
        .eq("slug", it.product_slug)
        .maybeSingle();
      const url = file?.storage_path
        ? await createSignedDownload(file.storage_path)
        : null;
      return {
        title: it.product_title,
        quantity: it.quantity,
        unitPriceChf: it.unit_price / 100,
        downloadUrl: url,
      };
    }),
  );

  await sendOrderConfirmation({
    to: order.customer_email,
    customerName: order.customer_name,
    orderId: order.id,
    totalChf: order.amount_total / 100,
    items: emailItems,
  });

  return NextResponse.json({ ok: true });
}
