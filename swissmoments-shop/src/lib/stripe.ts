import Stripe from "stripe";

/**
 * Server-only Stripe client. Lazy initialisiert, damit das Modul
 * auch ohne gesetzte Env-Var importierbar ist (z.B. während Build-Time).
 * Niemals im Browser importieren — der Secret-Key gehört nicht ins Bundle.
 */
let _stripe: Stripe | null = null;
export function getStripe(): Stripe {
  if (!_stripe) {
    const key = process.env.STRIPE_SECRET_KEY;
    if (!key) throw new Error("STRIPE_SECRET_KEY nicht gesetzt");
    _stripe = new Stripe(key, {
      apiVersion: "2025-02-24.acacia",
      typescript: true,
    });
  }
  return _stripe;
}

// Backwards-friendly Proxy, damit bestehende Aufrufer `stripe.foo.bar()`
// auch weiter funktionieren ohne explizit getStripe() zu rufen.
export const stripe = new Proxy({} as Stripe, {
  get(_target, prop) {
    return Reflect.get(getStripe(), prop);
  },
});

/** Preis in CHF (z.B. 14.9) → Rappen (z.B. 1490). */
export function chfToRappen(chf: number): number {
  return Math.round(chf * 100);
}
