"use client";

import { useState } from "react";
import { ShoppingBag } from "lucide-react";
import { useCart } from "@/lib/cart-context";
import { Button } from "@/components/ui/button";
import { startStripeCheckout } from "@/lib/checkout";
import type { Product } from "@/types";

interface Props {
  product: Product;
  variant?: "primary" | "buyNow";
  className?: string;
}

/**
 * Doppelte CTA-Komponente:
 *   - "primary" → Item in den Cart legen (öffnet Sidebar).
 *   - "buyNow"  → Direkt zum Stripe-Checkout mit nur diesem Produkt.
 *     Cart bleibt unangetastet.
 */
export function AddToCartButton({ product, variant = "primary", className }: Props) {
  const { addItem } = useCart();
  const [loading, setLoading] = useState(false);

  async function handleBuyNow() {
    setLoading(true);
    try {
      const url = await startStripeCheckout([
        {
          slug: product.slug,
          title: product.title,
          cover: product.cover,
          price: product.price,
          quantity: 1,
        },
      ]);
      window.location.href = url;
    } catch (err) {
      console.error(err);
      alert(
        "Der Checkout konnte gerade nicht gestartet werden. Bitte versuche es nochmal.",
      );
      setLoading(false);
    }
  }

  if (variant === "buyNow") {
    return (
      <Button
        variant="gold"
        size="lg"
        className={className}
        onClick={handleBuyNow}
        disabled={loading}
      >
        {loading ? "Wird vorbereitet…" : "Jetzt kaufen"}
      </Button>
    );
  }

  return (
    <Button size="lg" onClick={() => addItem(product)} className={className}>
      <ShoppingBag className="h-5 w-5" />
      In den Warenkorb
    </Button>
  );
}
