'use client';

import Link from 'next/link';
import { ArrowUpRight } from 'lucide-react';
import { useBank } from '@/lib/bank/store';
import { formatUSD, maskAccount } from '@/lib/bank/format';
import { TransactionTable } from '@/components/bank/transaction-table';

export default function OverviewPage() {
  const accounts = useBank((s) => s.accounts);
  const transactions = useBank((s) => s.transactions);
  const total = accounts.reduce((sum, a) => sum + a.balance, 0);

  return (
    <div className="space-y-10">
      <div className="flex items-end justify-between">
        <div>
          <div className="text-sm text-[#8792a2]">Total Liquidity</div>
          <div className="mt-1 text-3xl font-semibold tabular-nums tracking-tight">{formatUSD(total)}</div>
        </div>
        <Link
          href="/transfer"
          className="h-9 px-4 rounded-md bg-[#635bff] hover:bg-[#5851ea] text-white text-sm font-medium inline-flex items-center gap-1.5 shadow-sm"
        >
          <ArrowUpRight className="h-4 w-4" />
          Transfer Funds
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {accounts.map((a) => (
          <div key={a.id} className="rounded-lg bg-white border border-[#e6ebf1] p-5">
            <div className="flex justify-between text-sm">
              <span className="text-[#425466]">{a.name}</span>
              <span className="text-[#8792a2] tabular-nums">{maskAccount(a.number)}</span>
            </div>
            <div className="mt-3 text-xl font-semibold tabular-nums">{formatUSD(a.balance)}</div>
          </div>
        ))}
      </div>

      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold">Recent Transactions</h2>
          <Link href="/transactions" className="text-sm text-[#635bff] hover:text-[#0a2540]">
            View all
          </Link>
        </div>
        <div className="rounded-lg bg-white border border-[#e6ebf1] px-5">
          <TransactionTable items={transactions.slice(0, 5)} />
        </div>
      </section>
    </div>
  );
}
