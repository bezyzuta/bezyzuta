import type { Metadata } from "next";
import { Inter, Playfair_Display } from "next/font/google";
import Script from "next/script";
import { Header } from "@/components/header";
import { Footer } from "@/components/footer";
import { CartSidebar } from "@/components/cart-sidebar";
import { CartProvider } from "@/lib/cart-context";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});
const playfair = Playfair_Display({
  subsets: ["latin"],
  variable: "--font-playfair",
  display: "swap",
});

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "https://swissmoments.ch";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "SwissMoments – Nostalgische E-Books über die Schweiz von früher",
    template: "%s | SwissMoments",
  },
  description:
    "Tauche ein in die Schweizer Geschichte der 70er, 80er und 90er. Liebevoll gestaltete E-Books mit Geschichten, Bildern und Erinnerungen. Sofortiger Download.",
  keywords: [
    "Schweiz",
    "Nostalgie",
    "70er",
    "80er",
    "90er",
    "E-Book",
    "Geschichte",
    "Schweizer Tradition",
  ],
  authors: [{ name: "SwissMoments" }],
  openGraph: {
    title: "SwissMoments – Die gute alte Schweiz",
    description:
      "Liebevoll gestaltete E-Books über die Schweizer Nostalgie der 70er, 80er und 90er.",
    url: siteUrl,
    siteName: "SwissMoments",
    locale: "de_CH",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "SwissMoments – Die gute alte Schweiz",
    description:
      "Liebevoll gestaltete E-Books über die Schweizer Nostalgie der 70er, 80er und 90er.",
  },
};

// Strukturierte Daten — hilft Google, den Shop besser zu verstehen.
const organizationJsonLd = {
  "@context": "https://schema.org",
  "@type": "Organization",
  name: "SwissMoments",
  url: siteUrl,
  description:
    "Nostalgische E-Books über die Schweiz der 70er, 80er und 90er Jahre.",
  sameAs: ["https://www.tiktok.com/@swissmoments"],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="de-CH" className={`${inter.variable} ${playfair.variable}`}>
      <body className="min-h-screen bg-brand-cream font-sans text-brand-ink antialiased">
        <Script
          id="organization-jsonld"
          type="application/ld+json"
          // Sicher — wir kontrollieren den Inhalt vollständig.
          dangerouslySetInnerHTML={{
            __html: JSON.stringify(organizationJsonLd),
          }}
        />
        <CartProvider>
          <Header />
          <main>{children}</main>
          <Footer />
          <CartSidebar />
        </CartProvider>
      </body>
    </html>
  );
}
