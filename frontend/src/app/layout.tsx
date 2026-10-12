import type { Metadata } from "next";
import "./globals.css";
import { ClientProviders } from "@/components/shared/ClientProviders";

export const metadata: Metadata = {
  title: "Local AI — Your friendly AI studio",
  description: "Chat, create, and explore with your own team of local AI agents.",
  icons: { icon: "/local-ai-logo.svg", apple: "/local-ai-logo.svg" },
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
