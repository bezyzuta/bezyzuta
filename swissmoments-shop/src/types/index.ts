export type Decade = "70er" | "80er" | "90er";

export interface Product {
  /** URL-Slug — wird in /shop/[slug] verwendet. */
  slug: string;
  title: string;
  subtitle: string;
  /** Kurze Beschreibung für Cards (1–2 Sätze). */
  shortDescription: string;
  /** Lange Beschreibung für Produkt-Detailseite (Markdown-freier Fließtext). */
  longDescription: string;
  /** Bullet-Points: "Was drin ist". */
  contents: string[];
  decade: Decade;
  /** Preis in CHF. */
  price: number;
  /** Coverbild — public-relative Pfad oder absolute URL. */
  cover: string;
  /** Anzahl Seiten / Format / etc. — kleine Meta-Liste auf Detailseite. */
  meta: { label: string; value: string }[];
}

export interface CartItem {
  slug: string;
  title: string;
  cover: string;
  price: number;
  quantity: number;
}
