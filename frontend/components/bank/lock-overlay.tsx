'use client';

import { useEffect, useState } from 'react';
import { ShieldAlert } from 'lucide-react';
import { useBank } from '@/lib/bank/store';
import { releaseLock } from '@/lib/bank/guard';

export function LockOverlay() {
  const lock = useBank((s) => s.lock);
  const [verifying, setVerifying] = useState(false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!lock) return;
    // Swallow Enter/Space so a pressured user can't submit through the overlay.
    const block = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target?.dataset.allowKeys === 'true') return;
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        e.stopPropagation();
      }
    };
    window.addEventListener('keydown', block, true);
    return () => window.removeEventListener('keydown', block, true);
  }, [lock]);

  if (!lock) return null;

  const risk = Math.round(lock.riskScore * 100);

  const submit = async () => {
    if (!reason.trim()) return;
    setBusy(true);
    await releaseLock(lock.sessionId, reason.trim());
    setBusy(false);
  };

  return (
    <div className="fixed inset-0 z-50 bg-[#0a2540]/40 backdrop-blur-[2px] flex items-center justify-center p-6 animate-in fade-in duration-150">
      <div className="w-full max-w-md rounded-xl bg-white shadow-[0_30px_60px_-12px_rgba(50,50,93,0.35)] overflow-hidden">
        <div className="h-1 bg-[#df1b41]" />
        <div className="p-7">
          <div className="h-11 w-11 rounded-full bg-[#fff0f3] flex items-center justify-center">
            <ShieldAlert className="h-5 w-5 text-[#df1b41]" />
          </div>

          <h2 className="mt-5 text-lg font-semibold text-[#0a2540]">Transaction Frozen by Echo Zero-Trust</h2>
          <p className="mt-1.5 text-sm text-[#425466] leading-relaxed">
            Echo intercepted active executive impersonation and coercive wire fraud on your ongoing call. Wire settlement is frozen under CAEP RFC 9493.
          </p>

          {(risk > 0 || lock.reason) && (
            <div className="mt-5 rounded-lg border border-[#e6ebf1] divide-y divide-[#e6ebf1] text-sm">
              {risk > 0 && (
                <div className="flex justify-between px-4 py-2.5">
                  <span className="text-[#8792a2]">Risk Confidence</span>
                  <span className="font-medium text-[#df1b41]">{risk}%</span>
                </div>
              )}
              {lock.reason && <div className="px-4 py-2.5 text-[#425466]">{lock.reason}</div>}
            </div>
          )}

          {!verifying ? (
            <button
              onClick={() => setVerifying(true)}
              className="mt-6 text-sm text-[#635bff] hover:text-[#0a2540] font-medium"
            >
              Verified through secondary out-of-band channel?
            </button>
          ) : (
            <div className="mt-6 space-y-3">
              <input
                autoFocus
                data-allow-keys="true"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Audit notes (e.g. verified with executive via secure corporate phone)"
                className="w-full h-10 px-3 rounded-md border border-[#e6ebf1] text-sm outline-none focus:border-[#635bff] focus:ring-4 focus:ring-[#635bff]/10"
              />
              <div className="flex justify-end gap-2">
                <button
                  onClick={() => setVerifying(false)}
                  className="h-9 px-3.5 rounded-md text-sm text-[#425466] hover:bg-[#f6f9fc]"
                >
                  Cancel
                </button>
                <button
                  disabled={!reason.trim() || busy}
                  onClick={submit}
                  className="h-9 px-3.5 rounded-md text-sm font-medium bg-[#0a2540] text-white disabled:opacity-40"
                >
                  {busy ? 'Unlocking…' : 'Release Freeze'}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
