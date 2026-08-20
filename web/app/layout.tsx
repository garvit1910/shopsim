import type { Metadata } from "next";
import { Archivo_Black } from "next/font/google";
import Shell from "@/components/Shell";
import "./globals.css";

/** The 04 Graph aside's display face, from the pen. next/font self-hosts it at
 * build time, so the page makes no runtime request to fonts.googleapis.com. */
const archivo = Archivo_Black({
  weight: "400", subsets: ["latin"], display: "swap", variable: "--archivo",
});

export const metadata: Metadata = {
  title: "ShopSim — Simulated Ad Market",
  description: "Upload ads, run them against a synthetic shopper population, watch the market decide",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={archivo.variable}>
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
