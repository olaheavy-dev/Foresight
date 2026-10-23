import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import type { ReactNode } from "react";
import { THEME_INIT_SCRIPT } from "@/lib/theme";
import "./globals.css";

// Self-hosted from committed files (app/fonts): the build never fetches fonts, so a Google outage
// can't fail it, and pages make no requests to Google.
const inter = localFont({
  src: "./fonts/inter-latin-wght-normal.woff2",
  weight: "100 900",
  variable: "--font-inter",
  display: "swap",
});
const serif = localFont({
  src: [
    { path: "./fonts/source-serif-4-latin-wght-normal.woff2", weight: "200 900", style: "normal" },
    { path: "./fonts/source-serif-4-latin-wght-italic.woff2", weight: "200 900", style: "italic" },
  ],
  variable: "--font-source-serif",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Foresight · Your money, a few steps ahead",
  description: "Your money, a few steps ahead: forecasts, checked advice and a receipt for every number.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en-GB" className={`${inter.variable} ${serif.variable}`} suppressHydrationWarning>
      <head>
        {/* Applies the saved Light/Dark/System choice before first paint (no flash). Static. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
