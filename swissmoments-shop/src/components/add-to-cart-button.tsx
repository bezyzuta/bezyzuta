"use client";

import { ShoppingBag } from "lucide-react";
import { useCart } from "@/lib/cart-context";
import { Button } from "@/components/ui/button";
import { buildShopifyDirectCheckoutUrl, isShopifyEnabled } from "@/lib/shopify";
import type { Product } from "@/types";

interface Props {
  product: Product;
  variant?: "primary" | "buyNow";
  className?: string;
}

/**
 * Doppelte CTA-Komponente:
 *   - "primary" → Item in den Cart legen (öffnet Sidebar)
 *   - "buyNow"  → Direkt-Checkout. Wenn Shopify konfiguriert ist und eine
 *                  Variant ID vorliegt, springt der User direkt auf den
 *                  Shopify-Cart. Sonst Fallback in den lokalen Cart.
 */
export function AddToCartButton({ product, variant = "primary", className }: Props) {
  const { addItem } = useCart();

  if (variant === "buyNow") {
    return (
      <Button
        variant="gold"
        size="lg"
        className={className}
        onClick={() => {
          const directUrl =
            isShopifyEnabled() && product.shopifyVariantId
              ? buildShopifyDirectCheckoutUrl({
                  slug: product.slug,
                  title: product.title,
                  cover: product.cover,
                  price: product.price,
                  quantity: 1,
                  shopifyVariantId: product.shopifyVariantId,
                })
              : null;
          if (directUrl) {
            window.location.href = directUrl;
            return;
          }
          // Fallback: in den lokalen Cart und Sidebar öffnen.
          addItem(product);
        }}
      >
        Jetzt kaufen
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
