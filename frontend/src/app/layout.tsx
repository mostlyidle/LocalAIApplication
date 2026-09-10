import type { Metadata } from "next";
import "./globals.css";
import { ClientProviders } from "@/components/shared/ClientProviders";

export const metadata: Metadata = {
  title: "Local AI - Fully Local Intelligence",
  description: "Production-grade AI application running entirely on your Mac with Ollama",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="antialiased">
        <ClientProviders>{children}</ClientProviders>
      </body>
    </html>
  );
}
