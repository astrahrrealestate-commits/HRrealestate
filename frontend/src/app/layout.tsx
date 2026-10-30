import type { Metadata, Viewport } from "next";
import { Hanken_Grotesk, Bricolage_Grotesque, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { SuperAgentProvider } from "@/context/SuperAgentContext";

const hankenGrotesk = Hanken_Grotesk({
  variable: "--font-hanken",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

const bricolageGrotesque = Bricolage_Grotesque({
  variable: "--font-bricolage",
  subsets: ["latin"],
  weight: ["700"],
  display: "swap",
});

const ibmPlexMono = IBM_Plex_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "EstateOS | AI Property Management",
  description: "Minimal executive property management operating system for Harjot Singh.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${hankenGrotesk.variable} ${bricolageGrotesque.variable} ${ibmPlexMono.variable} h-full antialiased`}
    >
      <body className="min-h-dvh flex flex-col font-sans bg-[var(--bg)] text-[var(--ink)]">
        <SuperAgentProvider>{children}</SuperAgentProvider>
      </body>
    </html>
  );
}
