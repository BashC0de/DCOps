import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "DCOps Copilot",
  description: "Autonomous Multi-Site Data Center Operations Platform",
};

const NAV = [
  { href: "/", label: "Fleet" },
  { href: "/incidents", label: "Incidents" },
  { href: "/twin", label: "Twin" },
  { href: "/query", label: "Query" },
];

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <header className="border-b border-ink-100/10 bg-ink-900/60 backdrop-blur">
          <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
            <Link href="/" className="font-mono text-sm font-semibold tracking-tight">
              dcops<span className="text-accent-info">·</span>copilot
            </Link>
            <nav className="flex gap-6 text-sm">
              {NAV.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="text-ink-100/70 transition hover:text-ink-50"
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
