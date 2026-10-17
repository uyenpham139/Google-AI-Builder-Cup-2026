'use client';

import { Transaction } from '@/lib/bank/store';
import { formatDate, formatUSD, maskAccount } from '@/lib/bank/format';

export function StatusBadge({ status }: { status: Transaction['status'] }) {
  return status === 'succeeded' ? (
    <span className="inline-flex items-center h-5 px-1.5 rounded text-xs font-medium bg-[#d7f7c2] text-[#05690d]">
      Completed
    </span>
  ) : (
    <span className="inline-flex items-center h-5 px-1.5 rounded text-xs font-medium bg-[#ffe7f2] text-[#b3093c]">
      Frozen
    </span>
  );
}

export function TransactionTable({ items }: { items: Transaction[] }) {
  if (items.length === 0) {
    return <div className="py-16 text-center text-sm text-[#8792a2]">No transactions found</div>;
  }

  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-[#8792a2] border-b border-[#e6ebf1]">
          <th className="py-2.5 font-medium">Amount</th>
          <th className="py-2.5 font-medium" />
          <th className="py-2.5 font-medium">Recipient</th>
          <th className="py-2.5 font-medium">Description</th>
          <th className="py-2.5 font-medium text-right">Date</th>
        </tr>
      </thead>
      <tbody>
        {items.map((tx) => (
          <tr key={tx.id} className="border-b border-[#e6ebf1] last:border-0 hover:bg-[#f6f9fc]">
            <td className="py-3 pr-4 font-medium tabular-nums whitespace-nowrap">{formatUSD(tx.amount)}</td>
            <td className="py-3 pr-4">
              <StatusBadge status={tx.status} />
            </td>
            <td className="py-3 pr-4">
              <div className="text-[#0a2540]">{tx.recipient.name}</div>
              <div className="text-xs text-[#8792a2]">
                {tx.recipient.bank} · {maskAccount(tx.recipient.number)}
              </div>
            </td>
            <td className="py-3 pr-4 text-[#425466] max-w-[220px] truncate">{tx.note}</td>
            <td className="py-3 text-right text-[#8792a2] whitespace-nowrap tabular-nums">{formatDate(tx.createdAt)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
