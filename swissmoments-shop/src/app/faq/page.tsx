import type { Metadata } from "next";
import Link from "next/link";
import Script from "next/script";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = {
  title: "FAQ — Häufige Fragen",
  description:
    "Antworten zu Kauf, Download, Zahlung und Rückgabe der SwissMoments E-Books.",
};

const faqs = [
  {
    q: "Wie bekomme ich das E-Book nach dem Kauf?",
    a: "Direkt nach erfolgreichem Bezahlen bekommst du eine E-Mail mit deinem persönlichen Download-Link. Du kannst das E-Book als PDF (für jedes Gerät) und als EPUB (für Reader) sofort herunterladen.",
  },
  {
    q: "Auf welchen Geräten kann ich es lesen?",
    a: "Du kannst das E-Book auf jedem modernen Gerät lesen — Handy, Tablet, Laptop, E-Reader. PDF läuft überall, EPUB funktioniert besonders gut auf Kindle, Kobo und in iBooks.",
  },
  {
    q: "Welche Zahlungsmethoden akzeptiert ihr?",
    a: "Wir akzeptieren TWINT, Kreditkarte (Visa, Mastercard, Amex), Apple Pay, Google Pay und PayPal. Die Bezahlung läuft sicher über Shopify.",
  },
  {
    q: "Kann ich das E-Book zurückgeben?",
    a: "Mit dem Kauf eines digitalen Produkts verzichtest du auf das gesetzliche Rückgaberecht — die Datei ist nach dem Download sofort bei dir und kann nicht wirklich «zurückgegeben» werden. Solltest du trotzdem unzufrieden sein, melde dich innerhalb von 14 Tagen bei uns. Wir finden gemeinsam eine faire Lösung, versprochen.",
  },
  {
    q: "Ist das E-Book auf Schweizerdeutsch oder Hochdeutsch?",
    a: "Die Bücher sind in Hochdeutsch geschrieben, weil das für alle Schweizer gut lesbar ist. Wir verwenden aber bewusst Helvetismen (z. B. Velo, Znüni, Migros) — so fühlt es sich richtig zuhause an.",
  },
  {
    q: "Kann ich das E-Book verschenken?",
    a: "Sehr gerne. Schreib uns nach dem Kauf einfach eine kurze E-Mail an hallo@swissmoments.ch — wir stellen dir ein hübsches Gutscheindokument zum Ausdrucken zusammen.",
  },
  {
    q: "Werden weitere E-Books erscheinen?",
    a: "Auf jeden Fall. Wir arbeiten gerade an Bänden über die Schweizer Werbung, Schulzeit und Ferien — folge uns auf TikTok oder Instagram, um nichts zu verpassen.",
  },
  {
    q: "Kann ich euch Geschichten oder Bilder schicken?",
    a: "Ja, sehr gerne! Schick uns deine Erinnerungen an hallo@swissmoments.ch. Wenn wir sie ins nächste E-Book aufnehmen, bekommst du es selbstverständlich gratis.",
  },
  {
    q: "Wie hoch sind die Versandkosten?",
    a: "Da unsere E-Books digital sind, fallen keine Versandkosten an. Du bekommst alles direkt per E-Mail.",
  },
  {
    q: "Bekomme ich eine Rechnung?",
    a: "Ja. Nach dem Kauf erhältst du automatisch eine Rechnung als PDF per E-Mail. Auf Wunsch passen wir die Rechnungsangaben gerne für dich an.",
  },
];

export default function FaqPage() {
  const faqJsonLd = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: faqs.map((f) => ({
      "@type": "Question",
      name: f.q,
      acceptedAnswer: { "@type": "Answer", text: f.a },
    })),
  };

  return (
    <>
      <Script
        id="faq-jsonld"
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(faqJsonLd) }}
      />

      <div className="container py-14 md:py-20">
        <div className="mx-auto max-w-2xl text-center">
          <span className="vintage-divider mx-auto w-40 text-xs font-medium uppercase tracking-widest">
            Häufige Fragen
          </span>
          <h1 className="mt-4 font-serif text-4xl text-brand-ink md:text-5xl">
            FAQ
          </h1>
          <p className="mt-3 text-base text-brand-ink/70">
            Alles, was du zu Kauf, Download und Zahlung wissen musst. Du findest
            nicht, was du suchst? Schreib uns einfach.
          </p>
        </div>

        <div className="mx-auto mt-12 max-w-3xl rounded-2xl bg-white px-6 py-2 shadow-sm ring-1 ring-brand-ink/5 md:px-10">
          <Accordion type="single" collapsible className="w-full">
            {faqs.map((f, i) => (
              <AccordionItem key={f.q} value={`item-${i}`}>
                <AccordionTrigger>{f.q}</AccordionTrigger>
                <AccordionContent>{f.a}</AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </div>

        <div className="mx-auto mt-14 max-w-2xl rounded-2xl bg-brand-cream-dark/40 p-8 text-center ring-1 ring-brand-ink/5">
          <h2 className="font-serif text-2xl text-brand-ink">
            Frage nicht beantwortet?
          </h2>
          <p className="mt-2 text-brand-ink/70">
            Schreib uns — wir antworten meistens innerhalb von 24 Stunden.
          </p>
          <Button asChild className="mt-5">
            <Link href="mailto:hallo@swissmoments.ch">
              hallo@swissmoments.ch
            </Link>
          </Button>
        </div>
      </div>
    </>
  );
}
