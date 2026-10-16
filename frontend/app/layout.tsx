import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import { AppShell } from '@/components/bank/app-shell';
import './globals.css';

const inter = Inter({ subsets: ['latin'], variable: '--font-inter' });

export const metadata: Metadata = {
  title: 'Echo Business Banking',
  description: 'Corporate treasury & payments protected by Echo Zero-Trust AI.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} h-full antialiased`}>
      <body className="min-h-full font-sans">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
