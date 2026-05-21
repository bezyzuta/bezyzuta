"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Instagram, Mail } from "lucide-react";

function TikTokIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      className={className}
      aria-hidden="true"
    >
      <path d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-5.2 1.74 2.89 2.89 0 0 1 2.31-4.64 2.93 2.93 0 0 1 .88.13V9.4a6.84 6.84 0 0 0-1-.05A6.33 6.33 0 0 0 5.8 20.1a6.34 6.34 0 0 0 10.86-4.43V8.93a8.16 8.16 0 0 0 4.77 1.52V7a4.85 4.85 0 0 1-1.84-.31z" />
    </svg>
  );
}

export function Footer() {
  const pathname = usePathname();
  if (pathname?.startsWith("/admin")) return null;
  return (
    <footer className="mt-24 border-t border-brand-ink/10 bg-brand-cream-dark/40">
      <div className="container py-14">
        <div className="grid gap-12 md:grid-cols-4">
          <div className="md:col-span-2">
            <Link
              href="/"
              className="font-serif text-2xl font-semibold text-brand-ink"
            >
              <span className="text-brand-red">Swiss</span>Moments
            </Link>
            <p className="mt-3 max-w-md text-sm leading-relaxed text-brand-ink/70">
              Liebevoll gestaltete E-Books über die Schweiz der 70er, 80er und
              90er Jahre. Geschichten, Bilder und Erinnerungen, die ein ganzes
              Land geprägt haben.
            </p>
            <div className="mt-5 flex items-center gap-3">
              <a
                href="https://www.tiktok.com/@swissmomentsch"
                target="_blank"
                rel="noreferrer noopener"
                aria-label="SwissMoments auf TikTok"
                className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-brand-ink text-brand-cream transition-transform hover:scale-105"
              >
                <TikTokIcon className="h-4 w-4" />
              </a>
              <a
                href="https://www.instagram.com/"
                target="_blank"
                rel="noreferrer noopener"
                aria-label="SwissMoments auf Instagram"
                className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-brand-ink text-brand-cream transition-transform hover:scale-105"
              >
                <Instagram className="h-4 w-4" />
              </a>
              <a
                href="mailto:hallo@swissmoments.ch"
                aria-label="E-Mail an SwissMoments"
                className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-brand-ink text-brand-cream transition-transform hover:scale-105"
              >
                <Mail className="h-4 w-4" />
              </a>
            </div>
          </div>

          <div>
            <p className="font-serif text-sm font-semibold uppercase tracking-wider text-brand-ink">
              Shop
            </p>
            <ul className="mt-4 space-y-2 text-sm text-brand-ink/70">
              <li>
                <Link href="/shop" className="hover:text-brand-red">
                  Alle E-Books
                </Link>
              </li>
              <li>
                <Link href="/shop?decade=70er" className="hover:text-brand-red">
                  70er
                </Link>
              </li>
              <li>
                <Link href="/shop?decade=80er" className="hover:text-brand-red">
                  80er
                </Link>
              </li>
              <li>
                <Link href="/shop?decade=90er" className="hover:text-brand-red">
                  90er
                </Link>
              </li>
            </ul>
          </div>

          <div>
            <p className="font-serif text-sm font-semibold uppercase tracking-wider text-brand-ink">
              Mehr
            </p>
            <ul className="mt-4 space-y-2 text-sm text-brand-ink/70">
              <li>
                <Link href="/ueber-uns" className="hover:text-brand-red">
                  Über uns
                </Link>
              </li>
              <li>
                <Link href="/faq" className="hover:text-brand-red">
                  FAQ
                </Link>
              </li>
              <li>
                <Link href="/impressum" className="hover:text-brand-red">
                  Impressum
                </Link>
              </li>
              <li>
                <Link href="/datenschutz" className="hover:text-brand-red">
                  Datenschutz
                </Link>
              </li>
            </ul>
          </div>
        </div>

        <div className="mt-12 flex flex-col items-start justify-between gap-3 border-t border-brand-ink/10 pt-6 text-xs text-brand-ink/60 md:flex-row md:items-center">
          <p>
            © {new Date().getFullYear()} SwissMoments. Mit ❤️ aus der Schweiz.
          </p>
          <p>Sichere Zahlung via Shopify · Schweizer Franken (CHF)</p>
        </div>
      </div>
    </footer>
  );
}
