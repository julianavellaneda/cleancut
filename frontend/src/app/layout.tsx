import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-body",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AI Media Editor",
  description: "Simple AI-powered media editing",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased min-h-screen flex flex-col font-sans`}
      >
        <main className="flex-grow">
          {children}
        </main>
        <footer className="p-8 border-t text-center text-xs text-muted-foreground bg-background">
          <div className="flex justify-center gap-6">
            <span>© 2026 AI Media Editor</span>
            <a href="/admin" className="hover:text-foreground transition-colors">Admin Dashboard</a>
          </div>
        </footer>
      </body>
    </html>
  );
}
