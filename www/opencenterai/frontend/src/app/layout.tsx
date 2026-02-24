import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'OpenCenterAI — Trading Dashboard',
  description: 'ETH/USD Automated Trading with Claude AI',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="fr" className="dark" suppressHydrationWarning>
      <body className="min-h-screen bg-bg text-text antialiased" suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}
