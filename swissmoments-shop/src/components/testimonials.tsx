"use client";

import { motion } from "framer-motion";
import { Quote } from "lucide-react";

const testimonials = [
  {
    quote:
      "Ich habe das E-Book gekauft und in einem Rutsch durchgelesen. Genau so war meine Kindheit in Bern — danke für diesen wunderschönen Rückblick!",
    name: "Marlies B.",
    location: "Bern · 67",
  },
  {
    quote:
      "Wir haben es zusammen mit den Enkeln gelesen. Sie waren fasziniert, dass es einmal eine Schweiz ohne Smartphones gab. Tolles Geschenk!",
    name: "Hans R.",
    location: "Zürich · 71",
  },
  {
    quote:
      "Die Bilder, die Geschichten — alles so liebevoll zusammengestellt. Habe Tränen in den Augen gehabt. Sofort weiterempfohlen.",
    name: "Sandra K.",
    location: "Luzern · 54",
  },
  {
    quote:
      "Endlich ein Produkt aus der Schweiz, das nicht nur Käse und Schoggi verkauft. Die SwissMoments-Bücher sind kleine Schätze.",
    name: "Peter F.",
    location: "St. Gallen · 62",
  },
];

export function Testimonials() {
  return (
    <section className="container py-20 md:py-28">
      <div className="flex flex-col items-center text-center">
        <span className="vintage-divider w-44 text-xs font-medium uppercase tracking-widest">
          Was Leser sagen
        </span>
        <h2 className="mt-4 font-serif text-3xl text-brand-ink md:text-5xl">
          Stimmen aus der ganzen Schweiz
        </h2>
      </div>

      <div className="mt-14 grid gap-6 md:grid-cols-2">
        {testimonials.map((t, i) => (
          <motion.figure
            key={t.name}
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-50px" }}
            transition={{ duration: 0.5, delay: i * 0.08 }}
            className="relative rounded-2xl bg-white p-8 shadow-sm ring-1 ring-brand-ink/5"
          >
            <Quote className="absolute -top-3 left-6 h-8 w-8 rounded-full bg-brand-red p-2 text-white" />
            <blockquote className="font-serif text-lg leading-relaxed text-brand-ink">
              «{t.quote}»
            </blockquote>
            <figcaption className="mt-6 flex items-center gap-3">
              <span
                className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-brand-gold/30 font-serif text-sm font-semibold text-brand-ink"
                aria-hidden="true"
              >
                {t.name
                  .split(" ")
                  .map((p) => p[0])
                  .join("")
                  .slice(0, 2)}
              </span>
              <div>
                <p className="text-sm font-semibold text-brand-ink">{t.name}</p>
                <p className="text-xs text-brand-ink/60">{t.location}</p>
              </div>
            </figcaption>
          </motion.figure>
        ))}
      </div>
    </section>
  );
}
