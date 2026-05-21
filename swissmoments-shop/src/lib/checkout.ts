import type { CartItem } from "@/types";

/**
 * Frontend-Helper: postet den Cart an /api/checkout und holt die
 * Stripe-Checkout-URL. Beim Erfolg leitet der Aufrufer weiter.
 */
export async function startStripeCheckout(items: CartItem[]): Promise<string> {
  const res = await fetch("/api/checkout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      items: items.map((i) => ({
        slug: i.slug,
        quantity: i.quantity,
      })),
    }),
  });
  if (!res.ok) {
    const msg = await res.text();
    throw new Error(`Checkout fehlgeschlagen: ${msg || res.status}`);
  }
  const { url } = (await res.json()) as { url: string };
  if (!url) throw new Error("Checkout-URL fehlt");
  return url;
}
