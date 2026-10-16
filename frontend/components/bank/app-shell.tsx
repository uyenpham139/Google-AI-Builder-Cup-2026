'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Home, ArrowUpRight, ReceiptText, ShieldCheck, ShieldOff } from 'lucide-react';
import { useBank } from '@/lib/bank/store';
import { useGuardConnection } from '@/lib/bank/guard';
import { LockOverlay } from './lock-overlay';

const NAV = [
  { href: '/', label: 'Dashboard', icon: Home },
  { href: '/transfer', label: 'Transfer', icon: ArrowUpRight },
  { href: '/transactions', label: 'Transactions', icon: ReceiptText },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  useGuardConnection();
  const pathname = usePathname();
  const guardOnline = useBank((s) => s.guardOnline);

  return (
    <div className="min-h-screen flex bg-[#f6f9fc] text-[#0a2540]">
      <aside className="w-60 shrink-0 border-r border-[#e6ebf1] bg-white flex flex-col">
        <div className="h-16 px-5 flex items-center gap-2.5">
          <div className="h-7 w-7 rounded-md bg-[#635bff] text-white text-sm font-bold flex items-center justify-center">
            E
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold">Echo Corp</div>
            <div className="text-xs text-[#8792a2]">Treasury Portal</div>
          </div>
        </div>

        <nav className="px-3 py-2 space-y-0.5">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === '/' ? pathname === '/' : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={`flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors ${
                  active ? 'bg-[#f0f0ff] text-[#635bff] font-medium' : 'text-[#425466] hover:bg-[#f6f9fc] hover:text-[#0a2540]'
                }`}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto p-4 border-t border-[#e6ebf1]">
          <div className="flex items-center gap-2 text-xs text-[#425466]">
            {guardOnline ? (
              <ShieldCheck className="h-4 w-4 text-[#00a67e]" />
            ) : (
              <ShieldOff className="h-4 w-4 text-[#8792a2]" />
            )}
            <span>Echo Guard</span>
            <span className={`ml-auto h-1.5 w-1.5 rounded-full ${guardOnline ? 'bg-[#00a67e]' : 'bg-[#c1c9d2]'}`} />
          </div>
        </div>
      </aside>

      <main className="flex-1 min-w-0">
        <div className="max-w-5xl mx-auto px-10 py-10">{children}</div>
      </main>

      <LockOverlay />
    </div>
  );
}
