import type { Metadata, Viewport } from "next";
import "./globals.css";
import { SuperAgentProvider } from "@/context/SuperAgentContext";
import { AuthProvider } from "@/context/AuthContext";
import { LanguageProvider } from "@/context/LanguageContext";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { SectionGuard } from "@/components/layout/SectionGuard";
import { ApiHealthBanner } from "@/components/ui/ApiHealthBanner";

export const metadata: Metadata = {
  title: "HR Real Estate | AI Property Management",
  description: "Executive property management operating system for Harjot Singh.",
  icons: {
    icon: "/favicon.ico",
  },
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
    <html lang="en" className="h-full antialiased">
      <body className="min-h-dvh flex flex-col font-sans bg-[var(--bg)] text-[var(--ink)]">
        <LanguageProvider>
          <AuthProvider>
            <SuperAgentProvider>
              <ApiHealthBanner />
              <SectionGuard>{children}</SectionGuard>
              <CommandPalette />
            </SuperAgentProvider>
          </AuthProvider>
        </LanguageProvider>
      </body>
    </html>
  );
}
