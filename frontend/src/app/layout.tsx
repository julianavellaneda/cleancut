import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";

// Self-hosted rather than fetched from fonts.googleapis.com at build time.
// `next/font/google` downloads the face during `next build`, which made
// `docker compose build` fail on a machine with no network - or, worse, on a
// network that resolves but blocks the CDN, where it fails minutes in with a
// fetch error rather than at the point anyone would look. The two variable
// faces are committed under ./fonts (SIL OFL, see GEIST-LICENSE.txt); a build
// now needs nothing but the repo.
//
// Both are the variable-weight files, so one 70 KB face covers 100-900 and
// there is no per-weight list to keep in sync with the classes in use.
const geistSans = localFont({
  src: "./fonts/Geist-Variable.woff2",
  variable: "--font-body",
  weight: "100 900",
  display: "swap",
  fallback: ["ui-sans-serif", "system-ui", "sans-serif"],
});

const geistMono = localFont({
  src: "./fonts/GeistMono-Variable.woff2",
  variable: "--font-mono",
  weight: "100 900",
  display: "swap",
  fallback: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
});

export const metadata: Metadata = {
  title: "CleanCut",
  description: "Describe what to find in plain English, review it on a waveform, export a surgically edited file.",
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
