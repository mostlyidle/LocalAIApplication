import type { Metadata } from "next";
import "./globals.css";
import { ClientProviders } from "@/components/shared/ClientProviders";

export const metadata: Metadata = {
  title: "Mallow — Your local AI studio",
  description: "A cozy workspace for local chat, documents, research, and agents.",
  icons: { icon: "/local-ai-logo.svg" },
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
