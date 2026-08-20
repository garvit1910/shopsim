import type { Metadata } from "next";
import { Archivo_Black, Instrument_Serif, Martian_Mono } from "next/font/google";
import Shell from "@/components/Shell";
import "./globals.css";

/** The 04 Graph aside's display face, from the pen. next/font self-hosts it at
 * build time, so the page makes no runtime request to fonts.googleapis.com. */
const archivo = Archivo_Black({
  weight: "400", subsets: ["latin"], display: "swap", variable: "--archivo",
});

/** The landing byline's face. Italic only — it is a display cut that thins out
 * badly under ~19px, so nothing but the hero line and the two pull-quotes may
 * use it. Self-hosted at build time for the same reason Archivo is. */
const instrument = Instrument_Serif({
  weight: "400", style: "italic", subsets: ["latin"],
  display: "swap", variable: "--instrument",
});

/** The landing wordmark and its section headings. A wide grotesque monospace —
 * the display face for a product whose own stylesheet calls itself a terminal.
 * Landing-only; the cockpit stays on the system stacks. */
const martian = Martian_Mono({
  weight: "800", subsets: ["latin"], display: "swap", variable: "--martian",
});

export const metadata: Metadata = {
  title: "ShopSim — Simulated Ad Market",
  description: "Upload ads, run them against a synthetic shopper population, watch the market decide",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${archivo.variable} ${instrument.variable} ${martian.variable}`}>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
