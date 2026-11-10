import type { Metadata, Viewport } from "next";
import "./globals.css";
import { SuperAgentProvider } from "@/context/SuperAgentContext";
import { AuthProvider } from "@/context/AuthContext";
import { CommandPalette } from "@/components/layout/CommandPalette";

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
    <html lang="en" className="h-full antialiased">
      <body className="min-h-dvh flex flex-col font-sans bg-[var(--bg)] text-[var(--ink)]">
        <AuthProvider>
          <SuperAgentProvider>
            {children}
            <CommandPalette />
          </SuperAgentProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
