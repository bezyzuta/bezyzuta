import { Suspense } from "react";
import type { Metadata } from "next";
import { ShopPageContent } from "@/components/shop-page-content";

export const metadata: Metadata = {
  title: "Shop — Schweizer Nostalgie-E-Books",
  description:
    "Alle SwissMoments E-Books auf einen Blick. Filter nach Jahrzehnt (70er, 80er, 90er) und Preis. Sofortiger Download.",
};

export default function ShopPage() {
  return (
    <Suspense
      fallback={
        <div className="container py-20 text-center text-brand-ink/60">
          Lade Shop…
        </div>
      }
    >
      <ShopPageContent />
    </Suspense>
  );
}
