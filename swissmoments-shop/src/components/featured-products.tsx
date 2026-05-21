import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { ProductCard } from "@/components/product-card";
import { Button } from "@/components/ui/button";
import { products } from "@/lib/products";

export function FeaturedProducts() {
  const featured = products.slice(0, 4);

  return (
    <section id="featured" className="container py-20 md:py-28">
      <div className="flex flex-col items-center text-center">
        <span className="vintage-divider w-44 text-xs font-medium uppercase tracking-widest">
          Ausgewählt
        </span>
        <h2 className="mt-4 font-serif text-3xl text-brand-ink md:text-5xl">
          Ausgewählte Geschichten
        </h2>
        <p className="mt-3 max-w-xl text-base text-brand-ink/70">
          Unsere meistgekauften E-Books — kuratiert für alle, die ein Stück
          Schweiz von früher wieder mitnehmen wollen.
        </p>
      </div>

      <div className="mt-12 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {featured.map((product, i) => (
          <ProductCard key={product.slug} product={product} index={i} />
        ))}
      </div>

      <div className="mt-12 text-center">
        <Button asChild variant="outline" size="lg">
          <Link href="/shop">
            Alle E-Books ansehen
            <ArrowRight className="h-4 w-4" />
          </Link>
        </Button>
      </div>
    </section>
  );
}
