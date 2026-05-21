# SwissMoments Shop

Moderne, nostalgische E-Book-Shop-Website für **SwissMoments** – Schweizer
Geschichten aus den 70ern, 80ern und 90ern.

Gebaut mit **Next.js 15 (App Router), TypeScript, Tailwind CSS, Radix UI,
Framer Motion** und Lucide Icons. Bereit für eine 1-Klick-Anbindung an
**Shopify** (Storefront API oder Buy Buttons).

---

## Schnellstart

```bash
cd swissmoments-shop
npm install
npm run dev
```

Öffne dann <http://localhost:3000>.

## Build & Deploy (Vercel)

```bash
npm run build
npm run start
```

Für Vercel reicht:

1. Repository auf <https://vercel.com/new> verbinden.
2. **Root Directory** auf `swissmoments-shop` setzen (Monorepo-Subfolder).
3. **Environment Variables** (optional, später für Shopify) hinzufügen — siehe
   `.env.example`.
4. Deploy klicken. Fertig.

## Projekt-Struktur

```
swissmoments-shop/
├── src/
│   ├── app/
│   │   ├── page.tsx              # Homepage
│   │   ├── shop/page.tsx         # Shop mit Filter
│   │   ├── shop/[slug]/page.tsx  # Produkt-Detailseite
│   │   ├── ueber-uns/page.tsx    # Über uns
│   │   ├── faq/page.tsx          # FAQ mit Schema.org Markup
│   │   ├── layout.tsx            # Globales Layout + SEO
│   │   ├── sitemap.ts            # /sitemap.xml
│   │   ├── robots.ts             # /robots.txt
│   │   └── globals.css           # Tailwind + Brand-Variablen
│   ├── components/
│   │   ├── header.tsx / footer.tsx
│   │   ├── hero.tsx / featured-products.tsx / about-section.tsx / testimonials.tsx
│   │   ├── product-card.tsx
│   │   ├── add-to-cart-button.tsx
│   │   ├── cart-sidebar.tsx      # Mini-Cart (Radix Dialog)
│   │   ├── shop-page-content.tsx # Client-Komponente mit Filtern
│   │   └── ui/                   # button / accordion (shadcn-Style)
│   ├── lib/
│   │   ├── products.ts           # 6 Beispiel-E-Books (austauschbar)
│   │   ├── shopify.ts            # Storefront-API-Adapter (Stub)
│   │   ├── cart-context.tsx      # React Context + localStorage
│   │   └── utils.ts              # cn() + CHF-Formatter
│   └── types/index.ts
├── public/
├── tailwind.config.ts            # Brand-Farben (Rot #C8102E, Creme, Gold)
├── next.config.ts
└── SHOPIFY_INTEGRATION.md        # Schritt-für-Schritt-Anleitung
```

## Features

- ✅ Vollständig responsiv (Mobile-First für TikTok-Traffic)
- ✅ Warenkorb mit `localStorage`-Persistenz und Mini-Cart-Sidebar
- ✅ Filter nach Jahrzehnt (70er/80er/90er) und Preis
- ✅ Produkt-Detailseite mit Cross-Sell ("Passende Produkte")
- ✅ SEO: OpenGraph, Twitter Cards, JSON-LD (Organization, Book, FAQPage)
- ✅ Sitemap & robots.txt automatisch generiert
- ✅ Framer Motion-Animationen (sanft, nicht aufdringlich)
- ✅ Playfair Display (Serif) + Inter (Sans) via `next/font` (kein CLS)
- ✅ Next.js Image Optimization (Unsplash als Demo-CDN, Shopify CDN
  vorkonfiguriert)
- ✅ Shopify-Integration vorbereitet — siehe `SHOPIFY_INTEGRATION.md`

## Anpassung

**Produkte ändern:** `src/lib/products.ts` — füge / ändere die Einträge im
`products`-Array. Sobald Shopify aktiv ist, kannst du dieses Array durch
einen Storefront-API-Fetch ersetzen.

**Farben & Fonts:** `tailwind.config.ts` (Sektion `colors.brand` und
`fontFamily`) sowie die CSS-Variablen in `src/app/globals.css`.

**Texte:** Direkt in den jeweiligen Page-Komponenten — Homepage in
`src/app/page.tsx`, FAQ in `src/app/faq/page.tsx`, etc.

## Nächste Schritte

1. Lies `SHOPIFY_INTEGRATION.md` und verbinde deinen Shopify-Store.
2. Ersetze die Unsplash-Cover durch deine echten E-Book-Cover (lege sie in
   `public/covers/` und passe `cover` in `src/lib/products.ts` an).
3. Trage deine echten Social-Media-Links in `src/components/footer.tsx` ein.
4. Optional: Newsletter-Formular (z.B. Mailchimp / Brevo) hinzufügen.
