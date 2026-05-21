"use client";

import Link from "next/link";
import Image from "next/image";
import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

export function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div className="absolute inset-0 -z-10 bg-gradient-to-b from-brand-cream via-brand-cream to-brand-cream-dark/40" />
      <div className="absolute inset-0 -z-10 paper-grain opacity-70" />

      <div className="container grid items-center gap-12 py-16 md:grid-cols-2 md:py-24">
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7 }}
          className="max-w-xl"
        >
          <span className="inline-flex items-center gap-2 rounded-full border border-brand-red/20 bg-brand-red/5 px-4 py-1.5 text-xs font-medium uppercase tracking-wider text-brand-red">
            <span className="h-1.5 w-1.5 rounded-full bg-brand-red" />
            Schweizer Nostalgie · E-Books
          </span>

          <h1 className="mt-5 font-serif text-4xl leading-[1.1] text-brand-ink md:text-6xl">
            Die gute alte Schweiz
            <span className="block text-brand-red">in deinen Händen.</span>
          </h1>

          <p className="mt-6 max-w-lg text-lg leading-relaxed text-brand-ink/75">
            Liebevoll gestaltete E-Books über die 70er, 80er und 90er Jahre.
            Geschichten, Bilder und Erinnerungen, die uns geprägt haben — sofort
            zum Download.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Button asChild size="lg">
              <Link href="/shop">
                Jetzt entdecken
                <ArrowRight className="h-4 w-4" />
              </Link>
            </Button>
            <Button asChild size="lg" variant="outline">
              <Link href="/ueber-uns">Unsere Geschichte</Link>
            </Button>
          </div>

          <div className="mt-10 flex items-center gap-6 text-sm text-brand-ink/60">
            <div className="flex items-center gap-2">
              <span className="text-brand-gold">★★★★★</span>
              <span>4.9 von über 200 Lesern</span>
            </div>
            <div className="hidden sm:block">Sofortiger Download · PDF & EPUB</div>
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.8, delay: 0.1 }}
          className="relative mx-auto w-full max-w-md"
        >
          <div className="relative aspect-[4/5] overflow-hidden rounded-3xl shadow-2xl ring-1 ring-brand-ink/10">
            <Image
              src="https://images.unsplash.com/photo-1505934707-3deeae5c0d36?auto=format&fit=crop&w=900&q=80"
              alt="Vintage-Foto einer Schweizer Familie"
              fill
              priority
              sizes="(min-width: 768px) 400px, 80vw"
              className="object-cover"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-brand-ink/30 via-transparent" />
            <div className="absolute bottom-5 left-5 right-5 rounded-2xl bg-brand-cream/95 p-4 shadow-lg backdrop-blur">
              <p className="font-serif text-sm italic text-brand-ink">
                «Ich habe Tränen in den Augen. Genau so war es bei uns zuhause.»
              </p>
              <p className="mt-2 text-xs text-brand-ink/60">
                — Marlies, 67, aus Luzern
              </p>
            </div>
          </div>

          <div className="absolute -left-6 top-12 hidden h-24 w-24 rotate-[-8deg] rounded-md bg-brand-cream p-2 shadow-lg ring-1 ring-brand-ink/10 md:block">
            <div className="h-full w-full bg-brand-red/10" />
          </div>
          <div className="absolute -right-4 bottom-10 hidden h-20 w-20 rotate-6 rounded-md bg-brand-gold/30 p-2 shadow-lg md:block" />
        </motion.div>
      </div>
    </section>
  );
}
