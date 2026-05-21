import Image from "next/image";
import Link from "next/link";
import type { Metadata } from "next";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = {
  title: "Über uns",
  description:
    "Die Geschichte hinter SwissMoments: vom TikTok-Account zum nostalgischen E-Book-Shop für die Schweiz von früher.",
};

export default function AboutPage() {
  return (
    <div className="container py-14 md:py-20">
      <div className="mx-auto max-w-3xl text-center">
        <span className="vintage-divider mx-auto w-44 text-xs font-medium uppercase tracking-widest">
          Unsere Geschichte
        </span>
        <h1 className="mt-4 font-serif text-4xl text-brand-ink md:text-6xl">
          Aus Liebe zur Schweiz von früher
        </h1>
        <p className="mt-5 text-lg leading-relaxed text-brand-ink/75">
          SwissMoments ist als kleiner TikTok-Account gestartet — und ist heute
          ein Ort für alle, die die gute alte Schweiz nie ganz vergessen haben.
        </p>
      </div>

      <div className="mx-auto mt-14 grid max-w-5xl gap-12 md:grid-cols-2 md:items-center">
        <div className="relative aspect-[4/5] overflow-hidden rounded-3xl shadow-xl ring-1 ring-brand-ink/10">
          <Image
            src="https://images.unsplash.com/photo-1500382017468-9049fed747ef?auto=format&fit=crop&w=900&q=80"
            alt="Alte Schweizer Postkarten und Erinnerungsstücke"
            fill
            sizes="(min-width: 768px) 500px, 90vw"
            className="object-cover"
          />
        </div>

        <div className="space-y-5 text-base leading-relaxed text-brand-ink/80">
          <p>
            Alles begann mit einer alten Schachtel im Estrich meiner Grossmutter:
            Schwarzweiss-Fotos, Postkarten, ein paar abgenutzte
            Migros-Schoggi-Verpackungen. Während ich darin blätterte, merkte
            ich, wie sehr mich diese Welt berührt — und dachte: Das müssen
            mehr Menschen sehen.
          </p>
          <p>
            So entstand <strong>SwissMoments</strong> auf TikTok. Aus den
            ersten kleinen Videos wurden Tausende Follower, aus den Followern
            tausende Geschichten, die uns Leute aus der ganzen Schweiz erzählt
            haben. Es war klar: Diese Erinnerungen verdienen ein Zuhause.
          </p>
          <p>
            Heute machen wir aus diesen Geschichten liebevoll gestaltete
            E-Books — kuratiert, illustriert und in einer Form, die man sich
            jederzeit auf das Handy oder den Reader holen kann. Sie sind
            unsere kleine Hommage an die Schweiz der 70er, 80er und 90er.
          </p>
          <p className="font-serif italic text-brand-ink">
            Wir freuen uns, dass du hier bist.
          </p>
          <p className="text-sm text-brand-ink/60">— Das SwissMoments-Team</p>
        </div>
      </div>

      <div className="mx-auto mt-20 max-w-4xl rounded-3xl bg-brand-red px-8 py-12 text-center text-brand-cream shadow-xl md:px-12 md:py-16">
        <h2 className="font-serif text-3xl md:text-4xl">
          Folg uns auf TikTok
        </h2>
        <p className="mt-3 text-brand-cream/80">
          Täglich neue Geschichten, Bilder und Erinnerungen aus der Schweiz von
          früher.
        </p>
        <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
          <Button asChild variant="gold" size="lg">
            <a
              href="https://www.tiktok.com/@swissmoments"
              target="_blank"
              rel="noreferrer noopener"
            >
              @swissmoments auf TikTok
            </a>
          </Button>
          <Button
            asChild
            size="lg"
            variant="outline"
            className="border-brand-cream/40 text-brand-cream hover:bg-brand-cream/10"
          >
            <Link href="/shop">Shop entdecken</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
