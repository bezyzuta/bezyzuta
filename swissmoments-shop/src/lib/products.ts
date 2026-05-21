import type { Product } from "@/types";

/**
 * Startsortiment — der Produkt-Katalog ist file-based.
 *
 * Vorteile: keine zusätzliche DB-Tabelle nötig, sofort SEO-fähig (statisch
 * generiert), einfach via Git zu versionieren. Bei Änderungen einfach
 * deployen.
 *
 * Die zugehörige PDF-Datei wird über `products_files.slug = <slug>` in der
 * DB verknüpft (Admin-Upload), nicht hier hardcodiert.
 */
export const products: Product[] = [
  {
    slug: "die-vergessene-schweiz",
    title: "Die vergessene Schweiz",
    subtitle: "Bilder & Geschichten aus den 70ern",
    shortDescription:
      "Eine emotionale Reise zurück in die Schweiz der 70er Jahre – Orangina, Migros-Eier und das erste Farbfernsehen.",
    longDescription:
      "Die 70er Jahre waren in der Schweiz ein Jahrzehnt voller Umbrüche und gleichzeitig voller Geborgenheit. Familien sassen abends gemeinsam vor dem ersten Farbfernseher, im Quartier roch es nach frisch gebackenem Zopf, und der Sonntag gehörte dem Spaziergang. In diesem E-Book habe ich über 80 Geschichten, Anekdoten und nostalgische Bilder zusammengetragen, die viele von uns längst vergessen hatten – und die uns sofort wieder mitten in unsere Kindheit ziehen.",
    contents: [
      "Über 80 nostalgische Geschichten und Anekdoten",
      "Hochwertig kuratierte Bilder aus Schweizer Archiven",
      "Kapitel zu Alltag, Werbung, Musik und Fernsehen",
      "Persönliche Erinnerungen von Zeitzeugen",
      "Sofort-Download als PDF (über 120 Seiten)",
    ],
    decade: "70er",
    price: 14.9,
    cover:
      "https://images.unsplash.com/photo-1532009324734-20a7a5813719?auto=format&fit=crop&w=900&q=80",
    meta: [
      { label: "Format", value: "PDF / EPUB" },
      { label: "Seiten", value: "124" },
      { label: "Sprache", value: "Deutsch (CH)" },
    ],
  },
  {
    slug: "neon-und-walkman",
    title: "Neon & Walkman",
    subtitle: "Das Lebensgefühl der 80er",
    shortDescription:
      "Föhnfrisuren, Synth-Pop und der erste Walkman im Schulbus – die 80er Jahre, wie wir sie geliebt haben.",
    longDescription:
      "Niemand hat die Schweiz so geprägt wie die 80er. Plötzlich gab es Neonfarben in jedem Schaufenster, im Radio lief DRS 3 mit den neuesten Hits, und an jeder Bushaltestelle stand jemand mit Walkman und Kopfhörern auf den Ohren. Dieses E-Book sammelt die schönsten Momente, Werbespots, Mode-Trends und Musik-Erinnerungen dieses unvergleichlichen Jahrzehnts.",
    contents: [
      "Modedetails der 80er – von Schulterpolstern bis Föhnfrisur",
      "Werbespots, die uns nie wieder losgelassen haben",
      "Die wichtigsten Schweizer Bands und Hits des Jahrzehnts",
      "Spielzeug-Klassiker – von Lego Space bis Game & Watch",
      "Sofort-Download als PDF (über 140 Seiten)",
    ],
    decade: "80er",
    price: 16.9,
    cover:
      "https://images.unsplash.com/photo-1525373698358-041e3a460346?auto=format&fit=crop&w=900&q=80",
    meta: [
      { label: "Format", value: "PDF / EPUB" },
      { label: "Seiten", value: "142" },
      { label: "Sprache", value: "Deutsch (CH)" },
    ],
  },
  {
    slug: "swiss-90s",
    title: "Swiss 90s",
    subtitle: "Das letzte analoge Jahrzehnt",
    shortDescription:
      "Vom ersten Handy bis zum Pausenplatz mit Pokémon-Karten – die 90er Jahre, festgehalten in über 100 Geschichten.",
    longDescription:
      "Die 90er waren das letzte Jahrzehnt, in dem die Welt noch analog war – und gleichzeitig das erste, in dem das Internet leise an die Tür klopfte. In der Schweiz tauschten Kinder Pokémon-Karten, am Bahnhof Bern stand das erste Natel-D-Schild, und im TV liefen die Verkehrspolizisten. Dieses Buch ist ein liebevoller Rückblick auf ein Jahrzehnt zwischen Aufbruch und Geborgenheit.",
    contents: [
      "Pausenplatz-Klassiker, die jedes Kind kannte",
      "Die Geburtsstunde des Mobiltelefons in der Schweiz",
      "Game Boy, Tamagotchi und alles dazwischen",
      "Schweizer Kultserien und ihre besten Momente",
      "Sofort-Download als PDF (über 150 Seiten)",
    ],
    decade: "90er",
    price: 16.9,
    cover:
      "https://images.unsplash.com/photo-1495121605193-b116b5b9c5fe?auto=format&fit=crop&w=900&q=80",
    meta: [
      { label: "Format", value: "PDF / EPUB" },
      { label: "Seiten", value: "156" },
      { label: "Sprache", value: "Deutsch (CH)" },
    ],
  },
  {
    slug: "alpenland-erinnerungen",
    title: "Alpenland-Erinnerungen",
    subtitle: "Sommer, Berge und Familienferien",
    shortDescription:
      "Skiferien in Davos, Wanderungen mit Grossvater und das Picknick mit dem Cervelat – die schönsten Schweizer Sommer.",
    longDescription:
      "Es gibt einen Geruch, den jeder Schweizer kennt: warmes Gras, geschmolzener Schokoladenriegel und Sonnencreme – der Geruch der Sommerferien. Dieses E-Book taucht in die unvergesslichen Familienferien der 70er und 80er ein: Wanderungen, Übernachtungen im Bergrestaurant, das erste Mal Wasserski auf dem Vierwaldstättersee und Postkarten an die Grossmutter.",
    contents: [
      "Ferienorte, die jede Schweizer Familie kannte",
      "Klassiker aus dem Picknickkorb",
      "Lieder, die im Auto auf der Passhöhe gesungen wurden",
      "Wandertipps zu echten Geheim-Orten der 70er",
      "Sofort-Download als PDF (über 110 Seiten)",
    ],
    decade: "70er",
    price: 13.9,
    cover:
      "https://images.unsplash.com/photo-1527668752968-14dc70a27c95?auto=format&fit=crop&w=900&q=80",
    meta: [
      { label: "Format", value: "PDF / EPUB" },
      { label: "Seiten", value: "118" },
      { label: "Sprache", value: "Deutsch (CH)" },
    ],
  },
  {
    slug: "samichlaus-und-silvester",
    title: "Samichlaus & Silvester",
    subtitle: "Schweizer Feste, wie wir sie kannten",
    shortDescription:
      "Vom Samichlaus mit Mandarinen bis zum Silvester-Räuchern auf dem Land – ein Jahr voller Traditionen.",
    longDescription:
      "Ein Jahr in der Schweiz hatte einen ganz eigenen Rhythmus: im Frühling der Sechseläuten-Marsch, im Sommer das 1.-August-Feuer am See, im Herbst die Wegerwartung und im Winter der Samichlaus mit Erdnüssen und Mandarinen. In diesem E-Book habe ich Brauchtum aus allen Kantonen gesammelt – mit Bildern, Liedern und Rezepten zum Nachmachen.",
    contents: [
      "Traditionen aus allen Schweizer Kantonen",
      "Originalrezepte (Grittibänz, Magenbrot, u.v.m.)",
      "Lieder und Sprüche zum Mitsingen",
      "Geschichten von Zeitzeugen",
      "Sofort-Download als PDF (über 130 Seiten)",
    ],
    decade: "80er",
    price: 15.9,
    cover:
      "https://images.unsplash.com/photo-1543589077-47d81606c1bf?auto=format&fit=crop&w=900&q=80",
    meta: [
      { label: "Format", value: "PDF / EPUB" },
      { label: "Seiten", value: "134" },
      { label: "Sprache", value: "Deutsch (CH)" },
    ],
  },
  {
    slug: "schweizer-werbung",
    title: "Schweizer Werbung",
    subtitle: "Spots, die wir nie vergessen",
    shortDescription:
      "Von Henniez über Ovomaltine bis zur Migros – die Werbespots der 80er und 90er, die wir alle auswendig kennen.",
    longDescription:
      "Manche Werbespots wurden Teil unseres kollektiven Gedächtnisses. Wer kennt nicht 'Mit Ovomaltine kannst du's nicht besser, aber länger', den singenden Henniez-Strauss oder die Migros-Kassiererin? Dieses E-Book widmet sich liebevoll der goldenen Ära der Schweizer Werbung – mit Storyboards, Hintergrundgeschichten und Interviews mit den Machern.",
    contents: [
      "Die 30 bekanntesten Schweizer Spots der 80er & 90er",
      "Storyboards & Behind-the-Scenes-Bilder",
      "Werbe-Jingles als QR-Code zum direkt Anhören",
      "Interviews mit Werbern und Sprechern",
      "Sofort-Download als PDF (über 100 Seiten)",
    ],
    decade: "90er",
    price: 14.9,
    cover:
      "https://images.unsplash.com/photo-1521119989659-a83eee488004?auto=format&fit=crop&w=900&q=80",
    meta: [
      { label: "Format", value: "PDF / EPUB" },
      { label: "Seiten", value: "108" },
      { label: "Sprache", value: "Deutsch (CH)" },
    ],
  },
];

export function getProductBySlug(slug: string): Product | undefined {
  return products.find((p) => p.slug === slug);
}

export function getRelatedProducts(slug: string, limit = 3): Product[] {
  const current = getProductBySlug(slug);
  if (!current) return products.slice(0, limit);

  // Same decade first, then fill with anything else.
  const sameDecade = products.filter(
    (p) => p.slug !== slug && p.decade === current.decade,
  );
  const others = products.filter(
    (p) => p.slug !== slug && p.decade !== current.decade,
  );
  return [...sameDecade, ...others].slice(0, limit);
}
