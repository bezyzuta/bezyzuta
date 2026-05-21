import Image from "next/image";
import Link from "next/link";
import { BookOpen, Download, Heart } from "lucide-react";
import { Button } from "@/components/ui/button";

const reasons = [
  {
    icon: Heart,
    title: "Aus Liebe zur Heimat",
    text: "Jedes E-Book wird mit viel Herz und Sorgfalt von Schweizern für Schweizer gemacht.",
  },
  {
    icon: BookOpen,
    title: "Echte Geschichten",
    text: "Wir kuratieren Anekdoten, Bilder und Erinnerungen von Zeitzeugen aus allen Kantonen.",
  },
  {
    icon: Download,
    title: "Sofort verfügbar",
    text: "PDF & EPUB direkt nach dem Kauf — keine Wartezeit, keine Versandkosten.",
  },
];

export function AboutSection() {
  return (
    <section className="border-y border-brand-ink/10 bg-brand-cream-dark/40">
      <div className="container grid items-center gap-12 py-20 md:grid-cols-2 md:py-28">
        <div className="relative aspect-[4/3] overflow-hidden rounded-3xl shadow-xl ring-1 ring-brand-ink/10">
          <Image
            src="https://images.unsplash.com/photo-1519681393784-d120267933ba?auto=format&fit=crop&w=900&q=80"
            alt="Schweizer Alpenlandschaft in Sepia"
            fill
            sizes="(min-width: 768px) 500px, 90vw"
            className="object-cover"
          />
        </div>

        <div>
          <span className="vintage-divider w-44 text-xs font-medium uppercase tracking-widest">
            Über SwissMoments
          </span>
          <h2 className="mt-4 font-serif text-3xl text-brand-ink md:text-4xl">
            Warum SwissMoments?
          </h2>
          <p className="mt-4 max-w-lg text-base leading-relaxed text-brand-ink/75">
            Was als TikTok-Account angefangen hat, ist heute eine Sammlung von
            Geschichten, die ein ganzes Land berührt. Jedes E-Book ist ein
            kleiner Brief an die Schweiz von früher — und an alle, die diese
            Zeit nie ganz vergessen haben.
          </p>

          <ul className="mt-8 space-y-5">
            {reasons.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-4">
                <span className="inline-flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full bg-brand-red/10 text-brand-red">
                  <Icon className="h-5 w-5" />
                </span>
                <div>
                  <p className="font-serif text-lg text-brand-ink">{title}</p>
                  <p className="text-sm leading-relaxed text-brand-ink/70">
                    {text}
                  </p>
                </div>
              </li>
            ))}
          </ul>

          <Button asChild className="mt-8">
            <Link href="/ueber-uns">Mehr über uns</Link>
          </Button>
        </div>
      </div>
    </section>
  );
}
