import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Datenschutz",
  description:
    "Datenschutzerklärung von SwissMoments — wie wir mit deinen Daten umgehen (nach Schweizer DSG).",
};

/**
 * Datenschutzerklärung. Auf das Schweizer DSG / nDSG abgestimmt.
 *
 * ⚠️ TODO vor Go-Live ersetzen:
 *  - [FIRMENNAME] / [ADRESSE] in Abschnitt 1
 *  - Stand-Datum unten anpassen
 *
 * Diese Erklärung ist eine gute Basis, ersetzt aber keinen Anwalt.
 * Wenn du Mailchimp/Newsletter o.ä. ergänzt, hier nachführen.
 */
export default function DatenschutzPage() {
  return (
    <div className="container py-14 md:py-20">
      <div className="mx-auto max-w-2xl text-center">
        <span className="vintage-divider mx-auto w-44 text-xs font-medium uppercase tracking-widest">
          Rechtliches
        </span>
        <h1 className="mt-4 font-serif text-4xl text-brand-ink md:text-5xl">
          Datenschutzerklärung
        </h1>
        <p className="mt-3 text-base text-brand-ink/70">
          Wir nehmen den Schutz deiner persönlichen Daten sehr ernst und halten
          uns an die Vorgaben des Schweizer Datenschutzgesetzes (DSG / nDSG).
        </p>
      </div>

      <article className="mx-auto mt-12 max-w-3xl rounded-2xl bg-white px-6 py-10 shadow-sm ring-1 ring-brand-ink/5 md:px-12">
        <Section title="1. Verantwortliche Stelle">
          <p>
            <strong>SwissMoments</strong>
            <br />
            <Placeholder>[Firmenname / Inhaber]</Placeholder>
            <br />
            <Placeholder>[Strasse + Nr.]</Placeholder>
            <br />
            <Placeholder>[PLZ Ort]</Placeholder>
            <br />
            Schweiz
            <br />
            <br />
            E-Mail:{" "}
            <a
              href="mailto:hallo@swissmoments.ch"
              className="text-brand-red hover:underline"
            >
              hallo@swissmoments.ch
            </a>
          </p>
        </Section>

        <Section title="2. Welche Daten wir erheben">
          <p>Wir erheben und verarbeiten folgende Daten:</p>
          <Ul>
            <li>
              <strong>Bei einer Bestellung:</strong> Vor- und Nachname,
              E-Mail-Adresse, Rechnungsadresse, Bestelldetails (gekaufte
              E-Books, Preis, Bestelldatum).
            </li>
            <li>
              <strong>Zahlungsdaten</strong> werden ausschliesslich von unserem
              Zahlungsdienstleister Stripe verarbeitet — wir sehen Kartennummern
              o. ä. zu keinem Zeitpunkt.
            </li>
            <li>
              <strong>Bei Kontaktaufnahme</strong> (z. B. E-Mail): Name,
              E-Mail-Adresse und der Inhalt deiner Nachricht.
            </li>
            <li>
              <strong>Technische Daten beim Website-Besuch:</strong>
              IP-Adresse, Browsertyp, Zeitpunkt des Zugriffs (Server-Logs zur
              Sicherheit und Fehlerbehebung).
            </li>
          </Ul>
        </Section>

        <Section title="3. Zweck der Verarbeitung">
          <p>Deine Daten werden ausschliesslich verwendet, um</p>
          <Ul>
            <li>deine Bestellung abzuwickeln und die E-Books auszuliefern,</li>
            <li>
              dir die Bestätigungs- und Download-Mail sowie ggf. eine Rechnung
              zuzustellen,
            </li>
            <li>dich bei Rückfragen oder Support zu kontaktieren,</li>
            <li>
              gesetzlichen Aufbewahrungspflichten (z. B. im Steuerrecht)
              nachzukommen.
            </li>
          </Ul>
        </Section>

        <Section title="4. Auftragsverarbeiter / verwendete Dienste">
          <p>
            Für den Betrieb dieser Website setzen wir folgende Dienste ein.
            Diese verarbeiten in unserem Auftrag Daten und sind vertraglich an
            den Datenschutz gebunden:
          </p>
          <Ul>
            <li>
              <strong>Stripe Payments Europe Ltd.</strong> (Irland) — Abwicklung
              der Zahlungen (Kartenzahlung, TWINT, Apple Pay).
            </li>
            <li>
              <strong>Supabase Inc.</strong> (EU-Rechenzentrum) — Speicherung
              von Bestellungen und Auslieferung der E-Book-PDFs.
            </li>
            <li>
              <strong>Resend.com Inc.</strong> — Versand der Bestell- und
              Support-Mails.
            </li>
            <li>
              <strong>Vercel Inc.</strong> — Hosting der Website (Server-Logs,
              Auslieferung der Inhalte).
            </li>
          </Ul>
          <p className="mt-3 text-sm text-brand-ink/65">
            Eine Übermittlung deiner Daten ins Ausland (insbesondere EU/USA)
            kann durch diese Dienste erfolgen. Wir achten darauf, dass diese
            Anbieter ein angemessenes Datenschutzniveau garantieren.
          </p>
        </Section>

        <Section title="5. Cookies und lokaler Speicher">
          <p>
            Wir verwenden keine Tracking-Cookies und kein Werbe-Tracking. Für
            den Betrieb des Shops setzen wir zwei technisch notwendige
            Mechanismen ein:
          </p>
          <Ul>
            <li>
              Ein <strong>Cookie</strong> nach erfolgreichem Admin-Login (nur
              für uns intern relevant).
            </li>
            <li>
              <strong>localStorage</strong> in deinem Browser, um deinen
              Warenkorb zwischen Besuchen zu merken. Diese Daten verlassen
              deinen Browser nicht.
            </li>
          </Ul>
        </Section>

        <Section title="6. Weitergabe an Dritte">
          <p>
            Wir verkaufen deine Daten nicht. Eine Weitergabe erfolgt nur, wenn
            sie für die Vertragserfüllung notwendig ist (siehe Punkt 4) oder
            wenn wir gesetzlich dazu verpflichtet sind (z. B. auf Anordnung
            einer Schweizer Behörde).
          </p>
        </Section>

        <Section title="7. Aufbewahrungsdauer">
          <p>
            Bestelldaten bewahren wir während der gesetzlich vorgeschriebenen
            Frist von 10 Jahren auf (Schweizer Handelsrecht / OR Art. 958f).
            Andere Daten löschen wir, sobald sie für den Zweck der Verarbeitung
            nicht mehr nötig sind.
          </p>
        </Section>

        <Section title="8. Deine Rechte">
          <p>Du hast jederzeit das Recht auf:</p>
          <Ul>
            <li>Auskunft über die zu deiner Person gespeicherten Daten,</li>
            <li>Berichtigung oder Löschung deiner Daten,</li>
            <li>Einschränkung der Verarbeitung,</li>
            <li>Datenübertragbarkeit (Datenexport),</li>
            <li>Widerruf einer zuvor erteilten Einwilligung.</li>
          </Ul>
          <p className="mt-3">
            Schreib uns einfach an{" "}
            <a
              href="mailto:hallo@swissmoments.ch"
              className="text-brand-red hover:underline"
            >
              hallo@swissmoments.ch
            </a>{" "}
            — wir antworten meistens innert 24 Stunden.
          </p>
        </Section>

        <Section title="9. Änderungen dieser Erklärung">
          <p>
            Wir passen diese Datenschutzerklärung an, wenn sich rechtliche
            Anforderungen oder unsere Services ändern. Der aktuelle Stand
            findet sich immer hier auf dieser Seite.
          </p>
        </Section>

        <p className="mt-12 text-sm text-brand-ink/55">
          Stand: Mai 2026
        </p>
      </article>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-10 first:mt-0">
      <h2 className="font-serif text-xl text-brand-ink md:text-2xl">{title}</h2>
      <div className="mt-3 space-y-3 text-brand-ink/80 leading-relaxed">
        {children}
      </div>
    </section>
  );
}

function Ul({ children }: { children: React.ReactNode }) {
  return (
    <ul className="list-disc space-y-2 pl-6 marker:text-brand-red">
      {children}
    </ul>
  );
}

/** Sichtbarer Hinweis, dass dieser Wert vor Go-Live ersetzt werden muss. */
function Placeholder({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded bg-brand-gold/20 px-1.5 py-0.5 text-brand-ink">
      {children}
    </span>
  );
}
