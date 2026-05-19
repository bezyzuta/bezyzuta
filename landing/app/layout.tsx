import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "ClipForge — Aus langen Videos werden virale Shorts",
  description:
    "Lade ein Video hoch, ClipForge findet die viralsten Momente, schneidet sie und liefert YouTube-ready Shorts. KI-powered Pipeline für Creator.",
  metadataBase: new URL("https://clipforge.app"),
  openGraph: {
    title: "ClipForge — Aus langen Videos werden virale Shorts",
    description:
      "KI-powered Shorts-Pipeline. Lange Videos rein, virale Clips raus.",
    type: "website",
  },
};

export const viewport: Viewport = {
  themeColor: "#07070c",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="de" className={inter.variable}>
      <body>{children}</body>
    </html>
  );
}
