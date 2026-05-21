import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { Check, ChevronRight, Download, Shield, Star } from "lucide-react";
import { products, getProductBySlug, getRelatedProducts } from "@/lib/products";
import { formatPriceCHF } from "@/lib/utils";
import { AddToCartButton } from "@/components/add-to-cart-button";
import { ProductCard } from "@/components/product-card";
import Script from "next/script";

interface Params {
  slug: string;
}

export function generateStaticParams() {
  return products.map((p) => ({ slug: p.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  const { slug } = await params;
  const product = getProductBySlug(slug);
  if (!product) return { title: "Produkt nicht gefunden" };

  return {
    title: `${product.title} — ${product.subtitle}`,
    description: product.shortDescription,
    openGraph: {
      title: product.title,
      description: product.shortDescription,
      images: [{ url: product.cover, alt: product.title }],
      type: "website",
    },
  };
}

export default async function ProductPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { slug } = await params;
  const product = getProductBySlug(slug);
  if (!product) notFound();

  const related = getRelatedProducts(slug, 3);

  // Strukturierte Daten für Google Shopping / Rich Results.
  const productJsonLd = {
    "@context": "https://schema.org",
    "@type": "Book",
    name: product.title,
    description: product.shortDescription,
    image: product.cover,
    bookFormat: "https://schema.org/EBook",
    inLanguage: "de-CH",
    offers: {
      "@type": "Offer",
      priceCurrency: "CHF",
      price: product.price.toFixed(2),
      availability: "https://schema.org/InStock",
    },
  };

  return (
    <>
      <Script
        id={`product-${product.slug}-jsonld`}
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(productJsonLd) }}
      />

      <div className="container py-10 md:py-14">
        <nav
          aria-label="Brotkrumen"
          className="flex flex-wrap items-center gap-1 text-sm text-brand-ink/60"
        >
          <Link href="/" className="hover:text-brand-red">
            Start
          </Link>
          <ChevronRight className="h-3.5 w-3.5" />
          <Link href="/shop" className="hover:text-brand-red">
            Shop
          </Link>
          <ChevronRight className="h-3.5 w-3.5" />
          <span className="text-brand-ink">{product.title}</span>
        </nav>

        <div className="mt-8 grid gap-10 md:grid-cols-2 md:gap-14">
          <div className="relative">
            <div className="relative aspect-[3/4] overflow-hidden rounded-3xl bg-brand-cream-dark shadow-2xl ring-1 ring-brand-ink/10">
              <Image
                src={product.cover}
                alt={`Cover von ${product.title}`}
                fill
                priority
                sizes="(min-width: 768px) 500px, 90vw"
                className="object-cover"
              />
            </div>
            <span className="absolute left-4 top-4 rounded-full bg-brand-cream/95 px-4 py-1.5 text-xs font-semibold tracking-wide text-brand-ink shadow-sm">
              {product.decade}
            </span>
          </div>

          <div>
            <span className="text-xs font-semibold uppercase tracking-wider text-brand-red">
              {product.decade} · E-Book
            </span>
            <h1 className="mt-2 font-serif text-3xl text-brand-ink md:text-5xl">
              {product.title}
            </h1>
            <p className="mt-2 font-serif text-lg italic text-brand-ink/65">
              {product.subtitle}
            </p>

            <div className="mt-4 flex items-center gap-2 text-sm">
              <span className="flex text-brand-gold">
                {Array.from({ length: 5 }).map((_, i) => (
                  <Star key={i} className="h-4 w-4 fill-current" />
                ))}
              </span>
              <span className="text-brand-ink/60">
                4.9 · von Lesern empfohlen
              </span>
            </div>

            <p className="mt-6 text-base leading-relaxed text-brand-ink/80">
              {product.longDescription}
            </p>

            <div className="mt-8 rounded-2xl bg-white/60 p-6 ring-1 ring-brand-ink/5">
              <p className="font-serif text-lg text-brand-ink">Was drin ist</p>
              <ul className="mt-4 space-y-2.5">
                {product.contents.map((line) => (
                  <li
                    key={line}
                    className="flex items-start gap-3 text-sm text-brand-ink/80"
                  >
                    <Check className="mt-0.5 h-4 w-4 flex-shrink-0 text-brand-red" />
                    <span>{line}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="mt-8 flex items-baseline gap-3">
              <span className="font-serif text-4xl text-brand-red">
                {formatPriceCHF(product.price)}
              </span>
              <span className="text-sm text-brand-ink/55">inkl. MwSt.</span>
            </div>

            <div className="mt-5 flex flex-col gap-3 sm:flex-row">
              <AddToCartButton product={product} className="flex-1" />
              <AddToCartButton
                product={product}
                variant="buyNow"
                className="flex-1"
              />
            </div>

            <div className="mt-6 grid grid-cols-2 gap-3 text-xs text-brand-ink/65">
              <div className="flex items-center gap-2 rounded-lg bg-brand-cream-dark/40 px-3 py-2.5">
                <Download className="h-4 w-4 text-brand-red" />
                Sofort verfügbar nach Kauf
              </div>
              <div className="flex items-center gap-2 rounded-lg bg-brand-cream-dark/40 px-3 py-2.5">
                <Shield className="h-4 w-4 text-brand-red" />
                Sicherer Shopify-Checkout
              </div>
            </div>

            <dl className="mt-8 divide-y divide-brand-ink/10 border-y border-brand-ink/10">
              {product.meta.map((m) => (
                <div
                  key={m.label}
                  className="flex justify-between py-3 text-sm"
                >
                  <dt className="text-brand-ink/60">{m.label}</dt>
                  <dd className="font-medium text-brand-ink">{m.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>

        {related.length > 0 && (
          <section className="mt-24">
            <div className="text-center">
              <span className="vintage-divider mx-auto w-44 text-xs font-medium uppercase tracking-widest">
                Passende Produkte
              </span>
              <h2 className="mt-4 font-serif text-3xl text-brand-ink md:text-4xl">
                Das könnte dir auch gefallen
              </h2>
            </div>
            <div className="mt-10 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
              {related.map((p, i) => (
                <ProductCard key={p.slug} product={p} index={i} />
              ))}
            </div>
          </section>
        )}
      </div>
    </>
  );
}
