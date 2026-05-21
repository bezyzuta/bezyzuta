/**
 * Shopify-Integration — Platzhalter / Adapter.
 *
 * Diese Datei kapselt den Übergang von "statische Produkte" zu "echte Shopify
 * Produkte". Heute fallen alle Funktionen auf einen Demo-Flow zurück, sodass
 * die Seite ohne Shopify-Account voll funktioniert.
 *
 * Sobald du Shopify anbinden willst:
 * 1. Erstelle einen Shopify Storefront API Access Token
 *    (Shopify Admin → Apps → Headless / Hydrogen → Storefront API Tokens).
 * 2. Trage NEXT_PUBLIC_SHOPIFY_STORE_DOMAIN und
 *    NEXT_PUBLIC_SHOPIFY_STOREFRONT_ACCESS_TOKEN in `.env.local` ein.
 * 3. Fülle für jedes Produkt in `src/lib/products.ts` die `shopifyVariantId`
 *    aus (oder ersetze `products` durch einen Storefront-API-Fetch).
 * 4. `isShopifyEnabled()` wird dann automatisch true und der Checkout
 *    leitet auf shopify.com/checkout um.
 *
 * Siehe SHOPIFY_INTEGRATION.md für das volle Schritt-für-Schritt-HowTo.
 */

import type { CartItem } from "@/types";

const SHOPIFY_DOMAIN = process.env.NEXT_PUBLIC_SHOPIFY_STORE_DOMAIN;
const STOREFRONT_TOKEN =
  process.env.NEXT_PUBLIC_SHOPIFY_STOREFRONT_ACCESS_TOKEN;

export function isShopifyEnabled(): boolean {
  return Boolean(SHOPIFY_DOMAIN && STOREFRONT_TOKEN);
}

/**
 * Erstellt einen Shopify Cart und gibt die Checkout-URL zurück.
 *
 * Aktiv, sobald die Storefront-API konfiguriert ist UND jedes CartItem eine
 * gültige `shopifyVariantId` hat. Wir verwenden die moderne Cart API der
 * Storefront API (cartCreate Mutation).
 */
export async function createShopifyCheckout(items: CartItem[]): Promise<string | null> {
  if (!isShopifyEnabled()) return null;

  const missingVariant = items.find((i) => !i.shopifyVariantId);
  if (missingVariant) {
    console.warn(
      `[shopify] Variant ID fehlt für "${missingVariant.title}" — Shopify-Checkout übersprungen.`,
    );
    return null;
  }

  const query = `
    mutation cartCreate($input: CartInput!) {
      cartCreate(input: $input) {
        cart {
          id
          checkoutUrl
        }
        userErrors {
          field
          message
        }
      }
    }
  `;

  const variables = {
    input: {
      lines: items.map((i) => ({
        merchandiseId: i.shopifyVariantId,
        quantity: i.quantity,
      })),
    },
  };

  try {
    const res = await fetch(
      `https://${SHOPIFY_DOMAIN}/api/2024-10/graphql.json`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Shopify-Storefront-Access-Token": STOREFRONT_TOKEN!,
        },
        body: JSON.stringify({ query, variables }),
      },
    );
    const json = await res.json();
    const url = json?.data?.cartCreate?.cart?.checkoutUrl;
    return url ?? null;
  } catch (err) {
    console.error("[shopify] cartCreate failed", err);
    return null;
  }
}

/**
 * Buy-Button URL als zweite, einfachere Integrationsoption.
 *
 * Wenn du die Storefront API nicht einrichten willst, kannst du im Shopify
 * Admin pro Produkt einen "Buy Button" erstellen. Dieser hat einen direkten
 * Checkout-Link wie `https://your-store.myshopify.com/cart/<variantId>:1`.
 * Genau diese URL bauen wir hier für ein einzelnes Item.
 */
export function buildShopifyDirectCheckoutUrl(item: CartItem): string | null {
  if (!SHOPIFY_DOMAIN || !item.shopifyVariantId) return null;

  // Variant ID kann als globale ID kommen — wir extrahieren die rohe Zahl.
  const rawId = item.shopifyVariantId.split("/").pop();
  if (!rawId) return null;

  return `https://${SHOPIFY_DOMAIN}/cart/${rawId}:${item.quantity}`;
}
