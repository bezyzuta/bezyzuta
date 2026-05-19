# ClipForge — Landing Page

Modern Next.js 15 landing page for the ClipForge AI Shorts tool.

## Stack

- **Next.js 15** (App Router, React 19)
- **TypeScript** strict mode
- **Tailwind CSS v4** (CSS-based config, no `tailwind.config.ts`)
- **Framer Motion 11** for animations
- **Lucide React** for icons
- **shadcn/ui pattern** for the Button (no Radix dependency needed for what's used)

## Lokal starten

```bash
cd landing
npm install
npm run dev
```

Dann öffne [http://localhost:3000](http://localhost:3000).

Build & start in production-mode:

```bash
npm run build
npm start
```

## Design-Entscheidungen

### Farbschema
- **Background:** `#07070C` (near-black mit blauem Stich)
- **Surface:** `#0A0A12` (Cards, Mock-UI)
- **Primary:** Tailwind `purple-500` (`#A855F7`) — Hero-CTA, primäre Akzente
- **Accent:** Tailwind `cyan-400` (`#22D3EE`) — Live-Pulse, sekundäre Akzente
- **Gradients:** `purple-400 → fuchsia-400 → cyan-400` für Headlines, weniger sättigt für Borders

Pro Feature-Card hat einen anderen Accent (purple/cyan/violet/fuchsia rotierend), damit das Grid optisch nicht eintönig wird.

### Typografie
- **Inter** via `next/font/google` mit `--font-inter` CSS-Variable
- Headlines: `font-bold tracking-[-0.03em] leading-[0.95]` für tightes, modernes Look
- Body: `leading-relaxed text-balance` für Lesbarkeit

### Animationen
- Hero-Elemente staggered fade-up (delay 0.1s pro Element)
- Mock-UI: progressive Reveal (timeline → highlights → clips)
- Features: `whileInView` mit margin-bias damit Animation triggert bevor Card im Viewport ist
- Hover: Glow-shadow pro Accent-Farbe (custom shadow-[...] für genaues Tuning)

### Layout
- **Hero:** `min-h-screen` mit zentriertem Content, Mock-UI darunter
- **Features:** 1→2→4 Spalten responsive, `gap-4` für dichteres Grid

### Was NICHT drin ist (bewusst)
- Pricing-Section
- Testimonials
- Footer mit vielen Links (nur eine subtile Closing-Line)
- Cookie-Banner / Newsletter-Popup

## Struktur

```
landing/
├── app/
│   ├── globals.css       # Tailwind v4 import + Theme + Custom Utilities
│   ├── layout.tsx        # Root layout mit Inter font + metadata
│   └── page.tsx          # Composition: <Hero /> + <Features />
├── components/
│   ├── hero.tsx          # Hero mit Mock-UI-Preview
│   ├── features.tsx      # 8 Feature-Cards Grid
│   └── ui/
│       └── button.tsx    # shadcn-style Button (cva variants)
├── lib/
│   └── utils.ts          # cn() utility (clsx + tailwind-merge)
├── components.json       # shadcn config (falls du später Komponenten addest)
├── postcss.config.mjs    # @tailwindcss/postcss
├── tsconfig.json
├── next.config.ts
└── package.json
```

## Weitere Komponenten hinzufügen

Wenn du später z.B. einen Dialog oder Sheet brauchst:

```bash
npx shadcn@latest add dialog
```

`components.json` ist schon konfiguriert (style: new-york, baseColor: zinc).

## Branding ändern

**Name "ClipForge"** ist an 3 Stellen:
1. `app/layout.tsx` (metadata)
2. `components/hero.tsx` (Brand mark + Headline-Text)
3. `README.md`

**Farben** sind in `components/ui/button.tsx` und den Feature-Cards `accentMap` zentral.

**Default-Background-Farbe** in `app/globals.css` (`body { background-color: #07070c }`).

## Performance-Notes

- Next.js 15 mit React 19 → automatisch RSC wo möglich. `"use client"` ist nur auf `hero.tsx` und `features.tsx` weil sie Framer-Motion benutzen.
- Inter via `next/font/google` mit `display: swap` → kein FOIT.
- Keine Bilder im public-Folder (alles CSS/SVG) → kein LCP-Risiko.
- Mock-UI ist pure HTML/CSS — kein iframe, kein Video, kein extra Request.
