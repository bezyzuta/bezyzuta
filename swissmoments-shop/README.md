# SwissMoments Shop

Komplette E-Commerce-Site für **SwissMoments** — nostalgische Schweizer E-Books
der 70er, 80er und 90er. **Voll self-hosted**, kein Shopify nötig.

Stack: **Next.js 15** · TypeScript · Tailwind · Stripe Checkout · Supabase
(DB + Storage) · Resend (E-Mail) · Radix UI · Framer Motion.

---

## Schnellstart (lokal)

```bash
cd swissmoments-shop
cp .env.example .env.local       # dann ausfüllen (siehe SELFHOST_SETUP.md)
npm install
npm run dev
```

→ <http://localhost:3000> für den Shop · <http://localhost:3000/admin> für
das Backoffice.

## Build & Deploy auf Vercel

```bash
npm run build
```

Auf Vercel:
1. Repo verbinden.
2. **Root Directory** auf `swissmoments-shop` setzen (Monorepo-Subfolder).
3. Alle Environment Variables aus `.env.example` setzen (Stripe, Supabase,
   Resend, ADMIN_PASSWORD, SESSION_SECRET).
4. Deploy klicken.
5. Stripe-Webhook auf `https://<deine-domain>/api/webhook/stripe` setzen
   (siehe `SELFHOST_SETUP.md`).

## Was du bekommst

### Shop
- Homepage mit Hero, Featured-Produkten, About, Testimonials
- `/shop` mit Filter (Jahrzehnt, Preis) — URL-synchronisiert
- `/shop/[slug]` Produkt-Detail mit Cross-Sell + Schema.org `Book`-Markup
- `/ueber-uns`, `/faq` (mit FAQPage-JSON-LD)
- 404, `/sitemap.xml`, `/robots.txt`
- Warenkorb mit `localStorage`-Persistenz + Mini-Cart-Sidebar
- Mobile-First, Brand-Style: Rot/Creme/Gold, Playfair + Inter via `next/font`

### Self-hosted Checkout
- **Stripe Checkout** — Karten, TWINT, Apple/Google Pay (Locale `de`)
- Webhook-basierte Order-Fulfillment in Supabase
- Bestätigungs-Mail via **Resend** mit signierten Download-Links (7 Tage)
- `/order/success` zeigt die Downloads direkt nach dem Kauf an
- `/order/cancel` für abgebrochene Checkouts

### Admin (eingebaut)
- `/admin/login` — Passwort-basiertes Login (1 Operator)
- `/admin` — Dashboard: Umsatz, Bestellungen, fehlende PDFs
- `/admin/orders` — Letzte 100 Bestellungen mit "Email neu senden"-Button
- `/admin/products` — Pro Produkt PDF hochladen / ersetzen

## Projekt-Struktur

```
src/
├── app/
│   ├── (public pages)/         # Home, shop, ueber-uns, faq
│   ├── order/success|cancel/   # Post-Checkout
│   ├── admin/
│   │   ├── login/              # Login (kein Nav)
│   │   └── (authed)/           # Geschützte Pages mit Nav
│   └── api/
│       ├── checkout/           # POST → Stripe Session
│       ├── webhook/stripe/     # Fulfillment
│       └── admin/{login,logout,upload,resend-email}
├── components/
│   ├── (shop UI)/
│   ├── admin/
│   └── ui/                     # button, accordion (shadcn-style)
├── lib/
│   ├── stripe.ts               # Server-only Stripe Client
│   ├── supabase.ts             # Service-Role + signed download URLs
│   ├── email.ts                # Resend wrapper (Bestätigungsmail)
│   ├── admin-auth.ts           # Cookie-basierte Admin-Auth
│   ├── checkout.ts             # Frontend → /api/checkout
│   ├── products.ts             # File-based Katalog (6 E-Books)
│   ├── cart-context.tsx        # localStorage Warenkorb
│   └── utils.ts
├── types/index.ts
└── supabase/schema.sql         # DB-Setup (1x in Supabase laufen lassen)
```

## Datenfluss eines Verkaufs

```
Kunde klickt "Sicher zur Kasse"
  → POST /api/checkout (validiert Slug + Preis serverseitig)
  → Stripe Checkout Session erstellt
  → Kunde zahlt auf Stripe-Domain
  → Stripe redirect /order/success?session_id=...
  → Stripe POSTet /api/webhook/stripe (signature-verified)
       → Order + order_items in Supabase
       → Signierte Download-URLs aus Storage
       → Bestätigungsmail via Resend
```

Die Success-Page zieht direkt von Stripe + Storage — falls der Webhook
hinterherhinkt, sieht der Kunde trotzdem alles.

## Setup

→ Detaillierte Schritt-für-Schritt-Anleitung in
[`SELFHOST_SETUP.md`](./SELFHOST_SETUP.md).

## Anpassen

- **Produkte:** `src/lib/products.ts` (1 Eintrag pro E-Book)
- **Brand-Farben/Fonts:** `tailwind.config.ts` + `src/app/globals.css`
- **Texte:** in den jeweiligen Page-Dateien unter `src/app/`
- **Email-Design:** `src/lib/email.ts` (inlined HTML, einfach editierbar)
