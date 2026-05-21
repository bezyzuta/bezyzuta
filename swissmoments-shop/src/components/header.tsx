"use client";

import Link from "next/link";
import { useState } from "react";
import { usePathname } from "next/navigation";
import { Menu, ShoppingBag, X } from "lucide-react";
import { useCart } from "@/lib/cart-context";
import { Button } from "@/components/ui/button";

const nav = [
  { href: "/", label: "Start" },
  { href: "/shop", label: "Shop" },
  { href: "/ueber-uns", label: "Über uns" },
  { href: "/faq", label: "FAQ" },
];

export function Header() {
  const { totalQuantity, openCart } = useCart();
  const [mobileOpen, setMobileOpen] = useState(false);
  const pathname = usePathname();
  if (pathname?.startsWith("/admin")) return null;

  return (
    <header className="sticky top-0 z-40 border-b border-brand-ink/10 bg-brand-cream/85 backdrop-blur-md">
      <div className="container flex h-16 items-center justify-between md:h-20">
        <Link
          href="/"
          className="font-serif text-xl font-semibold tracking-tight text-brand-ink md:text-2xl"
          aria-label="SwissMoments — zur Startseite"
        >
          <span className="text-brand-red">Swiss</span>Moments
        </Link>

        <nav className="hidden items-center gap-8 md:flex">
          {nav.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="text-sm font-medium text-brand-ink/80 transition-colors hover:text-brand-red"
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={openCart}
            className="relative inline-flex h-10 w-10 items-center justify-center rounded-full text-brand-ink transition-colors hover:bg-brand-ink/5"
            aria-label={`Warenkorb öffnen (${totalQuantity} Artikel)`}
          >
            <ShoppingBag className="h-5 w-5" />
            {totalQuantity > 0 && (
              <span className="absolute -right-0.5 -top-0.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-brand-red px-1 text-xs font-semibold text-white">
                {totalQuantity}
              </span>
            )}
          </button>

          <Button
            asChild
            size="sm"
            className="hidden md:inline-flex"
          >
            <Link href="/shop">Jetzt entdecken</Link>
          </Button>

          <button
            type="button"
            onClick={() => setMobileOpen((v) => !v)}
            className="inline-flex h-10 w-10 items-center justify-center rounded-full text-brand-ink hover:bg-brand-ink/5 md:hidden"
            aria-label="Menü öffnen"
            aria-expanded={mobileOpen}
          >
            {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {mobileOpen && (
        <div className="border-t border-brand-ink/10 bg-brand-cream md:hidden">
          <nav className="container flex flex-col gap-1 py-4">
            {nav.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMobileOpen(false)}
                className="rounded-lg px-3 py-3 text-base font-medium text-brand-ink hover:bg-brand-ink/5"
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
      )}
    </header>
  );
}
