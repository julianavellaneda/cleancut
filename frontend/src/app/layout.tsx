import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Audio Compliance Review",
  description: "AI-powered audio compliance analysis for marketing guidelines",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased min-h-screen flex flex-col`}
      >
        <main className="flex-grow">
          {children}
        </main>
        <footer className="p-4 border-t text-center text-xs text-muted-foreground bg-background">
          <div className="flex justify-center gap-4">
            <span>© 2026 Audio Compliance Review</span>
            <a href="/admin" className="hover:underline">Admin</a>
          </div>
        </footer>
      </body>
    </html>
  );
}
