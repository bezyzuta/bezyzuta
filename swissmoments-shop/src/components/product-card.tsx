"use client";

import Image from "next/image";
import Link from "next/link";
import { motion } from "framer-motion";
import { ShoppingBag } from "lucide-react";
import type { Product } from "@/types";
import { useCart } from "@/lib/cart-context";
import { Button } from "@/components/ui/button";
import { formatPriceCHF } from "@/lib/utils";

interface Props {
  product: Product;
  /** index for stagger delay */
  index?: number;
}

export function ProductCard({ product, index = 0 }: Props) {
  const { addItem } = useCart();

  return (
    <motion.article
      initial={{ opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-50px" }}
      transition={{ duration: 0.5, delay: Math.min(index * 0.06, 0.4) }}
      className="group flex flex-col overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-brand-ink/5 transition-shadow hover:shadow-xl"
    >
      <Link
        href={`/shop/${product.slug}`}
        className="relative block aspect-[3/4] overflow-hidden bg-brand-cream-dark"
        aria-label={`${product.title} ansehen`}
      >
        <Image
          src={product.cover}
          alt={`Cover von ${product.title}`}
          fill
          sizes="(min-width: 1024px) 300px, (min-width: 640px) 45vw, 90vw"
          className="object-cover transition-transform duration-700 group-hover:scale-105"
        />
        <span className="absolute left-3 top-3 rounded-full bg-brand-cream/95 px-3 py-1 text-xs font-medium tracking-wide text-brand-ink shadow-sm">
          {product.decade}
        </span>
      </Link>

      <div className="flex flex-1 flex-col p-5">
        <h3 className="font-serif text-lg leading-snug text-brand-ink">
          <Link
            href={`/shop/${product.slug}`}
            className="transition-colors hover:text-brand-red"
          >
            {product.title}
          </Link>
        </h3>
        <p className="mt-1 text-sm italic text-brand-ink/60">
          {product.subtitle}
        </p>
        <p className="mt-3 line-clamp-3 text-sm leading-relaxed text-brand-ink/75">
          {product.shortDescription}
        </p>

        <div className="mt-5 flex items-center justify-between gap-3">
          <span className="font-serif text-xl text-brand-red">
            {formatPriceCHF(product.price)}
          </span>
          <Button
            size="sm"
            onClick={() => addItem(product)}
            aria-label={`${product.title} in den Warenkorb`}
          >
            <ShoppingBag className="h-4 w-4" />
            <span className="hidden sm:inline">In den Warenkorb</span>
            <span className="sm:hidden">Kaufen</span>
          </Button>
        </div>
      </div>
    </motion.article>
  );
}
