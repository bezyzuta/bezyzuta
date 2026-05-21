"use client";

import * as Dialog from "@radix-ui/react-dialog";
import Image from "next/image";
import Link from "next/link";
import { Minus, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";
import { useCart } from "@/lib/cart-context";
import { Button } from "@/components/ui/button";
import { formatPriceCHF } from "@/lib/utils";
import { startStripeCheckout } from "@/lib/checkout";

export function CartSidebar() {
  const {
    items,
    isOpen,
    closeCart,
    removeItem,
    updateQuantity,
    totalPrice,
    totalQuantity,
  } = useCart();
  const [checkoutLoading, setCheckoutLoading] = useState(false);

  async function handleCheckout() {
    if (items.length === 0) return;
    setCheckoutLoading(true);
    try {
      const url = await startStripeCheckout(items);
      window.location.href = url;
    } catch (err) {
      console.error(err);
      alert(
        "Der Checkout konnte gerade nicht gestartet werden. Bitte versuche es in einem Moment nochmal.",
      );
    } finally {
      setCheckoutLoading(false);
    }
  }

  return (
    <Dialog.Root open={isOpen} onOpenChange={(o) => !o && closeCart()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <Dialog.Content className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col bg-brand-cream shadow-2xl data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right data-[state=open]:animate-in data-[state=open]:slide-in-from-right data-[state=closed]:duration-200 data-[state=open]:duration-300">
          <div className="flex items-center justify-between border-b border-brand-ink/10 px-6 py-5">
            <Dialog.Title className="font-serif text-xl text-brand-ink">
              Dein Warenkorb
              {totalQuantity > 0 && (
                <span className="ml-2 text-sm font-normal text-brand-ink/60">
                  ({totalQuantity})
                </span>
              )}
            </Dialog.Title>
            <Dialog.Close asChild>
              <button
                className="inline-flex h-9 w-9 items-center justify-center rounded-full text-brand-ink hover:bg-brand-ink/5"
                aria-label="Warenkorb schliessen"
              >
                <X className="h-5 w-5" />
              </button>
            </Dialog.Close>
          </div>

          {items.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
              <p className="font-serif text-lg text-brand-ink">
                Dein Warenkorb ist noch leer.
              </p>
              <p className="mt-2 text-sm text-brand-ink/60">
                Stöbere durch unsere Geschichten und entdecke die gute alte
                Schweiz.
              </p>
              <Button asChild className="mt-6" onClick={closeCart}>
                <Link href="/shop">Zum Shop</Link>
              </Button>
            </div>
          ) : (
            <>
              <div className="flex-1 overflow-y-auto px-6 py-4">
                <ul className="divide-y divide-brand-ink/10">
                  {items.map((item) => (
                    <li key={item.slug} className="flex gap-4 py-4">
                      <div className="relative h-24 w-20 flex-shrink-0 overflow-hidden rounded-md bg-brand-cream-dark">
                        <Image
                          src={item.cover}
                          alt={item.title}
                          fill
                          className="object-cover"
                          sizes="80px"
                        />
                      </div>
                      <div className="flex flex-1 flex-col">
                        <Link
                          href={`/shop/${item.slug}`}
                          onClick={closeCart}
                          className="font-serif text-base text-brand-ink hover:text-brand-red"
                        >
                          {item.title}
                        </Link>
                        <p className="mt-1 text-sm text-brand-ink/60">
                          {formatPriceCHF(item.price)}
                        </p>
                        <div className="mt-auto flex items-center justify-between">
                          <div className="inline-flex items-center rounded-full border border-brand-ink/15">
                            <button
                              type="button"
                              onClick={() =>
                                updateQuantity(item.slug, item.quantity - 1)
                              }
                              className="inline-flex h-8 w-8 items-center justify-center text-brand-ink/70 hover:text-brand-red"
                              aria-label={`Menge von ${item.title} verringern`}
                            >
                              <Minus className="h-3.5 w-3.5" />
                            </button>
                            <span className="w-7 text-center text-sm font-medium">
                              {item.quantity}
                            </span>
                            <button
                              type="button"
                              onClick={() =>
                                updateQuantity(item.slug, item.quantity + 1)
                              }
                              className="inline-flex h-8 w-8 items-center justify-center text-brand-ink/70 hover:text-brand-red"
                              aria-label={`Menge von ${item.title} erhöhen`}
                            >
                              <Plus className="h-3.5 w-3.5" />
                            </button>
                          </div>
                          <button
                            type="button"
                            onClick={() => removeItem(item.slug)}
                            className="inline-flex h-8 w-8 items-center justify-center rounded-full text-brand-ink/50 hover:bg-brand-red/10 hover:text-brand-red"
                            aria-label={`${item.title} entfernen`}
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="border-t border-brand-ink/10 px-6 py-5">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-brand-ink/70">
                    Zwischensumme
                  </span>
                  <span className="font-serif text-xl text-brand-ink">
                    {formatPriceCHF(totalPrice)}
                  </span>
                </div>
                <p className="mt-1 text-xs text-brand-ink/50">
                  Steuern werden im Checkout berechnet · sofortiger Download
                </p>
                <Button
                  className="mt-4 w-full"
                  size="lg"
                  onClick={handleCheckout}
                  disabled={checkoutLoading}
                >
                  {checkoutLoading
                    ? "Wird vorbereitet…"
                    : "Sicher zur Kasse"}
                </Button>
                <button
                  type="button"
                  onClick={closeCart}
                  className="mt-2 w-full text-center text-sm text-brand-ink/60 hover:text-brand-red"
                >
                  Weiter stöbern
                </button>
              </div>
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
