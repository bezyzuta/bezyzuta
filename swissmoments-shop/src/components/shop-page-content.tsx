"use client";

import { useMemo, useState, useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { ProductCard } from "@/components/product-card";
import { Button } from "@/components/ui/button";
import { products } from "@/lib/products";
import type { Decade } from "@/types";
import { cn } from "@/lib/utils";

const DECADES: ("Alle" | Decade)[] = ["Alle", "70er", "80er", "90er"];
const PRICE_RANGES = [
  { label: "Alle", min: 0, max: Infinity },
  { label: "Bis CHF 15", min: 0, max: 15 },
  { label: "CHF 15–20", min: 15, max: 20 },
  { label: "Über CHF 20", min: 20, max: Infinity },
];

export function ShopPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const initialDecade =
    (searchParams.get("decade") as Decade | null) ?? null;

  const [decade, setDecade] = useState<"Alle" | Decade>(
    initialDecade ?? "Alle",
  );
  const [priceIdx, setPriceIdx] = useState(0);

  // Sync URL when filter changes (für teilbare Links).
  useEffect(() => {
    const params = new URLSearchParams();
    if (decade !== "Alle") params.set("decade", decade);
    const qs = params.toString();
    router.replace(qs ? `/shop?${qs}` : "/shop", { scroll: false });
  }, [decade, router]);

  const filtered = useMemo(() => {
    const range = PRICE_RANGES[priceIdx];
    return products.filter((p) => {
      const decadeOk = decade === "Alle" || p.decade === decade;
      const priceOk = p.price >= range.min && p.price <= range.max;
      return decadeOk && priceOk;
    });
  }, [decade, priceIdx]);

  return (
    <div className="container py-12 md:py-16">
      <div className="text-center">
        <span className="vintage-divider mx-auto w-44 text-xs font-medium uppercase tracking-widest">
          Alle Geschichten
        </span>
        <h1 className="mt-4 font-serif text-4xl text-brand-ink md:text-5xl">
          Unser Shop
        </h1>
        <p className="mx-auto mt-3 max-w-xl text-base text-brand-ink/70">
          Stöbere durch unsere E-Books und finde deine eigene Schweizer
          Lieblings-Ära.
        </p>
      </div>

      <div className="mt-10 flex flex-col gap-6 rounded-2xl bg-white/60 p-5 ring-1 ring-brand-ink/5 md:flex-row md:items-center md:justify-between md:p-6">
        <div>
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-brand-ink/60">
            Jahrzehnt
          </p>
          <div className="flex flex-wrap gap-2">
            {DECADES.map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDecade(d)}
                className={cn(
                  "rounded-full px-4 py-2 text-sm font-medium transition-colors",
                  decade === d
                    ? "bg-brand-red text-white shadow"
                    : "bg-brand-cream-dark/60 text-brand-ink hover:bg-brand-cream-dark",
                )}
              >
                {d}
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-brand-ink/60">
            Preis
          </p>
          <div className="flex flex-wrap gap-2">
            {PRICE_RANGES.map((r, i) => (
              <button
                key={r.label}
                type="button"
                onClick={() => setPriceIdx(i)}
                className={cn(
                  "rounded-full px-4 py-2 text-sm font-medium transition-colors",
                  priceIdx === i
                    ? "bg-brand-ink text-brand-cream shadow"
                    : "bg-brand-cream-dark/60 text-brand-ink hover:bg-brand-cream-dark",
                )}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <p className="mt-6 text-sm text-brand-ink/60">
        {filtered.length} {filtered.length === 1 ? "Geschichte" : "Geschichten"}
      </p>

      {filtered.length === 0 ? (
        <div className="mt-12 rounded-2xl bg-white p-12 text-center ring-1 ring-brand-ink/5">
          <p className="font-serif text-xl text-brand-ink">
            Keine Treffer für deine Auswahl.
          </p>
          <Button
            variant="outline"
            className="mt-6"
            onClick={() => {
              setDecade("Alle");
              setPriceIdx(0);
            }}
          >
            Filter zurücksetzen
          </Button>
        </div>
      ) : (
        <div className="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((p, i) => (
            <ProductCard key={p.slug} product={p} index={i} />
          ))}
        </div>
      )}
    </div>
  );
}
