'use client';

import { useState } from 'react';
import { useBank, TxStatus } from '@/lib/bank/store';
import { TransactionTable } from '@/components/bank/transaction-table';

const FILTERS: { id: 'all' | TxStatus; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'succeeded', label: 'Completed' },
  { id: 'blocked', label: 'Frozen by Echo' },
];

export default function TransactionsPage() {
  const transactions = useBank((s) => s.transactions);
  const [filter, setFilter] = useState<'all' | TxStatus>('all');
  const items = filter === 'all' ? transactions : transactions.filter((t) => t.status === filter);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Transactions</h1>

      <div className="flex gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            onClick={() => setFilter(f.id)}
            className={`h-8 px-3 rounded-full text-sm border transition-colors ${
              filter === f.id
                ? 'border-[#635bff] text-[#635bff] bg-[#f0f0ff]'
                : 'border-[#e6ebf1] text-[#425466] bg-white hover:border-[#c1c9d2]'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="rounded-lg bg-white border border-[#e6ebf1] px-5">
        <TransactionTable items={items} />
      </div>
    </div>
  );
}
