export function formatUSD(n: number): string {
  return `$${Math.round(n).toLocaleString('en-US')}`;
}

export const formatVND = formatUSD; // Backward-compatibility alias

export function formatDigits(digits: string): string {
  if (!digits) return '';
  return Number(digits).toLocaleString('en-US');
}

const dateFmt = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
});

export function formatDate(ts: number): string {
  return dateFmt.format(new Date(ts));
}

export function maskAccount(n: string): string {
  return `•••• ${n.replace(/\D/g, '').slice(-4)}`;
}
