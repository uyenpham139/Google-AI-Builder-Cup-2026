'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { Check, Plus, ShieldAlert, BadgeCheck } from 'lucide-react';
import { BANKS, Recipient, Transaction, useBank } from '@/lib/bank/store';
import { formatDigits, formatUSD, maskAccount } from '@/lib/bank/format';
import { isLedgerLocked } from '@/lib/bank/guard';
import { numberToEnglishWords } from '@/lib/number-to-words';

type Step = 'form' | 'confirm' | 'processing' | 'done' | 'blocked';

const inputCls =
  'w-full h-10 px-3 rounded-md border border-[#e6ebf1] bg-white text-sm text-[#0a2540] outline-none shadow-[0_1px_1px_rgba(0,0,0,0.03)] focus:border-[#635bff] focus:ring-4 focus:ring-[#635bff]/10 placeholder:text-[#a3acb9]';

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block mb-1.5 text-sm font-medium text-[#425466]">{label}</span>
      {children}
    </label>
  );
}

function initials(name: string) {
  return name
    .replace(/^(Inc\.|LLC|Corp\.|Corporation)\s+/i, '')
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0])
    .join('')
    .toUpperCase();
}

export default function TransferPage() {
  const { accounts, recipients, recordTransfer, lock } = useBank();

  const [step, setStep] = useState<Step>('form');
  const [accountId, setAccountId] = useState(accounts[0].id);
  const [recipientId, setRecipientId] = useState<string | 'new'>(recipients[0].id);
  const [newRecipient, setNewRecipient] = useState({ bank: BANKS[0], number: '', name: '' });
  const [digits, setDigits] = useState('');
  const [note, setNote] = useState('');
  const [otp, setOtp] = useState('');
  const [result, setResult] = useState<Transaction | null>(null);
  const recordedRef = useRef(false);

  const account = accounts.find((a) => a.id === accountId)!;
  const saved = recipients.find((r) => r.id === recipientId);
  const recipient: Omit<Recipient, 'id'> = saved ?? { ...newRecipient, verified: false };
  const amount = Number(digits || 0);
  const fee = 0;

  const canContinue =
    amount > 0 && amount <= account.balance && note.trim() && recipient.number.trim() && recipient.name.trim();

  const finish = (status: Transaction['status']) => {
    if (recordedRef.current) return;
    recordedRef.current = true;
    const tx = recordTransfer({ accountId, recipient, amount, note: note.trim(), status });
    setResult(tx);
    setStep(status === 'succeeded' ? 'done' : 'blocked');
  };

  // An Echo lock arriving mid-flow aborts the transfer before funds move.
  useEffect(() => {
    if (lock && (step === 'confirm' || step === 'processing')) finish('blocked');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lock, step]);

  const submitOtp = async () => {
    setStep('processing');
    await new Promise((r) => setTimeout(r, 1200));
    if (useBank.getState().lock || (await isLedgerLocked())) {
      finish('blocked');
    } else {
      finish('succeeded');
    }
  };

  const reset = () => {
    recordedRef.current = false;
    setStep('form');
    setDigits('');
    setNote('');
    setOtp('');
    setResult(null);
  };

  if ((step === 'done' || step === 'blocked') && result) {
    const ok = step === 'done';
    return (
      <div className="max-w-md mx-auto pt-10 text-center">
        <div
          className={`mx-auto h-12 w-12 rounded-full flex items-center justify-center ${
            ok ? 'bg-[#d7f7c2] text-[#05690d]' : 'bg-[#ffe7f2] text-[#df1b41]'
          }`}
        >
          {ok ? <Check className="h-6 w-6" /> : <ShieldAlert className="h-6 w-6" />}
        </div>
        <h1 className="mt-5 text-xl font-semibold">{ok ? 'Transfer Successful' : 'Transaction Intercepted & Frozen'}</h1>
        <p className="mt-1 text-sm text-[#425466]">
          {ok ? `Sent to ${result.recipient.name}` : 'Zero-Trust defense prevented capital flight. Funds remain secure.'}
        </p>
        <div className="mt-6 text-3xl font-semibold tabular-nums">{formatUSD(result.amount)}</div>
        <div className="mt-1 text-xs text-[#8792a2] tabular-nums">{result.ref}</div>

        <div className="mt-8 flex justify-center gap-2">
          <Link href="/" className="h-9 px-4 rounded-md border border-[#e6ebf1] bg-white text-sm font-medium inline-flex items-center hover:bg-[#f6f9fc]">
            Dashboard
          </Link>
          <button onClick={reset} className="h-9 px-4 rounded-md bg-[#635bff] hover:bg-[#5851ea] text-white text-sm font-medium cursor-pointer">
            New Transfer
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold tracking-tight">Transfer Funds</h1>

      <div className="grid grid-cols-[1fr_340px] gap-10 items-start">
        {/* LEFT: form or confirmation */}
        <div className="space-y-7">
          {step === 'form' ? (
            <>
              <Field label="From Account">
                <div className="grid grid-cols-2 gap-3">
                  {accounts.map((a) => (
                    <button
                      type="button"
                      key={a.id}
                      onClick={() => setAccountId(a.id)}
                      className={`text-left rounded-md border px-3.5 py-3 transition-shadow ${
                        a.id === accountId
                          ? 'border-[#635bff] ring-4 ring-[#635bff]/10 bg-white'
                          : 'border-[#e6ebf1] bg-white hover:border-[#c1c9d2]'
                      }`}
                    >
                      <div className="text-sm text-[#0a2540]">{a.name}</div>
                      <div className="mt-0.5 text-xs text-[#8792a2] tabular-nums">
                        {maskAccount(a.number)} · {formatUSD(a.balance)}
                      </div>
                    </button>
                  ))}
                </div>
              </Field>

              <Field label="Recipient">
                <div className="flex flex-wrap gap-2">
                  {recipients.map((r) => (
                    <button
                      type="button"
                      key={r.id}
                      onClick={() => setRecipientId(r.id)}
                      className={`h-9 pl-1 pr-3 rounded-full border inline-flex items-center gap-2 text-sm transition-colors ${
                        recipientId === r.id
                          ? 'border-[#635bff] bg-[#f0f0ff] text-[#0a2540]'
                          : 'border-[#e6ebf1] bg-white text-[#425466] hover:border-[#c1c9d2]'
                      }`}
                    >
                      <span className="h-7 w-7 rounded-full bg-[#e3e8ee] text-[10px] font-semibold text-[#425466] flex items-center justify-center">
                        {initials(r.name)}
                      </span>
                      <span className="max-w-[160px] truncate">{r.name}</span>
                    </button>
                  ))}
                  <button
                    type="button"
                    onClick={() => setRecipientId('new')}
                    className={`h-9 px-3 rounded-full border border-dashed inline-flex items-center gap-1.5 text-sm ${
                      recipientId === 'new'
                        ? 'border-[#635bff] text-[#635bff] bg-[#f0f0ff]'
                        : 'border-[#c1c9d2] text-[#425466] hover:text-[#0a2540]'
                    }`}
                  >
                    <Plus className="h-3.5 w-3.5" />
                    New
                  </button>
                </div>
              </Field>

              {recipientId === 'new' && (
                <div className="grid grid-cols-2 gap-4 -mt-2">
                  <Field label="Beneficiary Bank">
                    <select
                      value={newRecipient.bank}
                      onChange={(e) => setNewRecipient({ ...newRecipient, bank: e.target.value })}
                      className={inputCls}
                    >
                      {BANKS.map((b) => (
                        <option key={b}>{b}</option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Account / Routing Number">
                    <input
                      inputMode="numeric"
                      value={newRecipient.number}
                      onChange={(e) => setNewRecipient({ ...newRecipient, number: e.target.value.replace(/\D/g, '') })}
                      className={`${inputCls} tabular-nums`}
                    />
                  </Field>
                  <div className="col-span-2">
                    <Field label="Beneficiary Entity Name">
                      <input
                        value={newRecipient.name}
                        onChange={(e) => setNewRecipient({ ...newRecipient, name: e.target.value.toUpperCase() })}
                        className={inputCls}
                        placeholder="e.g. OFFSHORE ESCROW SERVICES LLC"
                      />
                    </Field>
                  </div>
                </div>
              )}

              <Field label="Transfer Amount">
                <div className="relative">
                  <input
                    inputMode="numeric"
                    value={formatDigits(digits)}
                    onChange={(e) => setDigits(e.target.value.replace(/\D/g, '').slice(0, 15))}
                    placeholder="0"
                    className={`${inputCls} h-12 text-lg font-medium pr-10 tabular-nums`}
                  />
                  <span className="absolute right-3.5 top-1/2 -translate-y-1/2 text-[#8792a2]">$</span>
                </div>
                <div className="mt-1.5 min-h-4 text-xs text-[#8792a2]">
                  {amount > account.balance ? (
                    <span className="text-[#df1b41]">Exceeds available balance</span>
                  ) : amount > 0 ? (
                    numberToEnglishWords(amount)
                  ) : null}
                </div>
              </Field>

              <Field label="Payment Memo / Reference">
                <input
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  className={inputCls}
                  placeholder="e.g. Urgent offshore escrow acquisition settlement"
                  maxLength={140}
                />
              </Field>

              <button
                disabled={!canContinue}
                onClick={() => setStep('confirm')}
                className="w-full h-11 rounded-md bg-[#635bff] hover:bg-[#5851ea] text-white text-sm font-medium shadow-sm disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              >
                Continue to Review
              </button>
            </>
          ) : (
            <div className="rounded-lg bg-white border border-[#e6ebf1] p-7">
              <h2 className="text-base font-semibold">Security Verification (2FA)</h2>
              <p className="mt-1 text-sm text-[#425466]">Enter the 6-digit one-time authorization code sent to your registered security key.</p>

              <input
                autoFocus
                inputMode="numeric"
                value={otp}
                disabled={step === 'processing'}
                onChange={(e) => setOtp(e.target.value.replace(/\D/g, '').slice(0, 6))}
                placeholder="••••••"
                className={`${inputCls} mt-5 h-12 text-center text-xl tracking-[0.5em] tabular-nums`}
              />

              <div className="mt-6 flex gap-2">
                <button
                  disabled={step === 'processing'}
                  onClick={() => setStep('form')}
                  className="h-10 px-4 rounded-md border border-[#e6ebf1] text-sm font-medium hover:bg-[#f6f9fc] disabled:opacity-40 cursor-pointer"
                >
                  Back
                </button>
                <button
                  disabled={otp.length < 6 || step === 'processing'}
                  onClick={submitOtp}
                  className="flex-1 h-10 rounded-md bg-[#635bff] hover:bg-[#5851ea] text-white text-sm font-medium disabled:opacity-40 cursor-pointer"
                >
                  {step === 'processing' ? 'Broadcasting & Verifying…' : `Authorize ${formatUSD(amount)} Wire`}
                </button>
              </div>
            </div>
          )}
        </div>

        {/* RIGHT: summary */}
        <aside className="rounded-lg bg-white border border-[#e6ebf1] p-6 sticky top-10">
          <div className="text-sm text-[#8792a2]">Total Wire Amount</div>
          <div className="mt-1 text-2xl font-semibold tabular-nums">{formatUSD(amount + fee)}</div>

          <dl className="mt-6 space-y-3 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-[#8792a2]">Beneficiary</dt>
              <dd className="text-right text-[#0a2540]">
                {recipient.name || '—'}
                {recipient.name &&
                  (recipient.verified ? (
                    <BadgeCheck className="inline h-4 w-4 ml-1 -mt-0.5 text-[#635bff]" />
                  ) : (
                    <span className="ml-1.5 text-xs text-[#c84801]">Unverified</span>
                  ))}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-[#8792a2]">Bank</dt>
              <dd className="text-[#0a2540]">{recipient.bank}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-[#8792a2]">Account Number</dt>
              <dd className="text-[#0a2540] tabular-nums">{recipient.number || '—'}</dd>
            </div>
            <div className="pt-3 border-t border-[#e6ebf1] flex justify-between gap-4">
              <dt className="text-[#8792a2]">Wire Fee</dt>
              <dd className="text-[#0a2540] tabular-nums">{formatUSD(fee)}</dd>
            </div>
          </dl>
        </aside>
      </div>
    </div>
  );
}
