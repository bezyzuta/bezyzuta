"use client";

import { useEffect } from "react";
import { useCart } from "@/lib/cart-context";

/**
 * Kleiner Helper: leert den Cart, sobald die Success-Page gerendert wird.
 * Schützt davor, dass ein Refresh nochmal denselben Cart-Inhalt anzeigt.
 */
export function ClearCartOnMount() {
  const { clearCart } = useCart();
  useEffect(() => {
    clearCart();
  }, [clearCart]);
  return null;
}
