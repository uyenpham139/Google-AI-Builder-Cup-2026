"use client";

import { useEffect, useState } from "react";
import { canApprove, connectLockdownChannel, type LockInfo } from "@/lib/lockdown/channel";

const EVENTS_URL =
  process.env.NEXT_PUBLIC_BACKEND_WS_URL?.replace(/\/ws\/audio$/, "/ws/events") ?? "ws://localhost:8000/ws/events";

function readSessionId(): string {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get("sessionId") ?? "";
}

export default function ErpPortalPage() {
  const [sessionId] = useState(readSessionId);
  // Once set, the lock is never replaced or cleared: there is no unfreeze flow.
  const [lock, setLock] = useState<LockInfo | null>(null);
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    const channel = connectLockdownChannel({
      url: EVENTS_URL,
      sessionId,
      onLock: (info) => setLock((prev) => prev ?? info),
    });
    return () => channel.close();
  }, [sessionId]);

  const approve = () => {
    // Checked again here, so re-enabling the button in dev tools still sends nothing.
    if (!canApprove(lock)) return;
    setSubmitted(true); // mock portal: no request leaves the page
  };

  const locked = !canApprove(lock);

  return (
    <main className="mx-auto flex min-h-screen max-w-lg flex-col gap-4 bg-slate-950 p-6 text-slate-100">
      <h1 className="text-2xl font-semibold">Treasury Portal (mock ERP)</h1>
      <p className="text-sm text-slate-400">
        Session: <span suppressHydrationWarning>{sessionId || "none (add ?sessionId=...)"}</span>
      </p>

      {locked && (
        <div role="alert" className="rounded-lg border border-rose-500 bg-rose-950 p-4 text-sm text-rose-100">
          <p className="font-bold">GIAO DỊCH ĐÃ BỊ PHONG TỎA AN NINH</p>
          <p className="mt-1">
            Phát hiện giả mạo lãnh đạo (risk {Math.round((lock?.riskScore ?? 0) * 100)}%). Mọi thao tác duyệt chi đã bị
            khóa; cần xác thực ngoài băng để mở khóa.
          </p>
        </div>
      )}

      <section className="rounded-xl border border-slate-800 bg-slate-900 p-6">
        <dl className="mb-4 grid grid-cols-2 gap-2 text-sm">
          <dt className="text-slate-400">Payment order</dt>
          <dd>Wire transfer, USD 25,000,000</dd>
          <dt className="text-slate-400">Requested by</dt>
          <dd>CEO (verbal instruction)</dd>
        </dl>
        <fieldset disabled={locked} className="space-y-3">
          <button
            id="btn-approve-payment"
            type="button"
            onClick={approve}
            disabled={locked}
            className={`w-full rounded-lg py-3 font-bold ${
              locked
                ? "cursor-not-allowed border border-rose-900 bg-slate-800 text-slate-500"
                : "bg-blue-600 text-white hover:bg-blue-500"
            }`}
          >
            {locked ? "GIAO DỊCH ĐÃ BỊ PHONG TỎA AN NINH" : "Ký Số & Phê Duyệt Lệnh Chi"}
          </button>
        </fieldset>
        {submitted && !locked && <p className="mt-3 text-sm text-emerald-400">Mock approval recorded (no request sent).</p>}
      </section>
    </main>
  );
}
