import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { THEME_STORAGE_KEY } from "@/lib/theme";

// Self-hosted rather than fetched from fonts.googleapis.com at build time.
// `next/font/google` downloads the face during `next build`, which made
// `docker compose build` fail on a machine with no network - or, worse, on a
// network that resolves but blocks the CDN, where it fails minutes in with a
// fetch error rather than at the point anyone would look. All three faces are
// committed under ./fonts (SIL OFL, see the *-LICENSE.txt beside them); a build
// now needs nothing but the repo.
//
// Figtree and GeistMono are the variable-weight files, so one face covers the
// whole range and there is no per-weight list to keep in sync with the classes
// in use. Caprasimo ships in a single weight by design - it is the display face
// and is only ever set at 400.
const figtree = localFont({
  src: "./fonts/Figtree-Variable.woff2",
  variable: "--font-body",
  weight: "300 900",
  display: "swap",
  fallback: ["ui-sans-serif", "system-ui", "sans-serif"],
});

const caprasimo = localFont({
  src: "./fonts/Caprasimo-Regular.woff2",
  variable: "--font-display",
  weight: "400",
  display: "swap",
  fallback: ["Georgia", "ui-serif", "serif"],
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

// Stamps `data-theme` before first paint. It has to be inline and synchronous:
// a `useEffect` runs after the browser has already painted the light ground, so
// a dark-mode user gets a lavender flash on every navigation. Nothing is
// stamped when there is no stored choice - the `prefers-color-scheme` block in
// globals.css is what answers then, and writing "dark" here on the OS's behalf
// would freeze a preference the user never expressed.
const NO_FLASH_THEME_SCRIPT = `
try {
  var t = localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});
  if (t === "light" || t === "dark") {
    document.documentElement.setAttribute("data-theme", t);
  }
} catch (e) {}
`.trim();

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: NO_FLASH_THEME_SCRIPT }} />
      </head>
      <body
        className={`${figtree.variable} ${caprasimo.variable} ${geistMono.variable} antialiased min-h-screen flex flex-col font-sans`}
      >
        {/*
          The footer that used to sit here is gone - the mockup has none. Its
          Admin link moved into the home header as "Maintenance", which is what
          keeps /admin reachable without it.
        */}
        <main className="flex-grow">
          {children}
        </main>
      </body>
    </html>
  );
}
