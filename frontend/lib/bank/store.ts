import { create } from 'zustand';

export interface Account {
  id: string;
  name: string;
  number: string;
  balance: number;
}

export interface Recipient {
  id: string;
  name: string;
  bank: string;
  number: string;
  verified: boolean;
}

export type TxStatus = 'succeeded' | 'blocked';

export interface Transaction {
  id: string;
  ref: string;
  accountId: string;
  recipient: Omit<Recipient, 'id'>;
  amount: number;
  note: string;
  status: TxStatus;
  createdAt: number;
}

export interface GuardLock {
  sessionId: string;
  reason: string;
  riskScore: number;
  at: number;
}

export const BANKS = [
  'JPMorgan Chase',
  'Bank of America',
  'Citibank',
  'Wells Fargo',
  'Goldman Sachs',
  'Barclays',
  'Standard Chartered'
];

const SEED_ACCOUNTS: Account[] = [
  { id: 'acc_main', name: 'Operating Treasury Account', number: '0071000988214', balance: 18_750_000 },
  { id: 'acc_reserve', name: 'Strategic Liquidity Reserve', number: '1903882144012', balance: 5_000_000 },
];

const SEED_RECIPIENTS: Recipient[] = [
  { id: 'r1', name: 'Global Logistics Partners Inc.', bank: 'JPMorgan Chase', number: '0011004488912', verified: true },
  { id: 'r2', name: 'AWS Enterprise Cloud Services', bank: 'Silicon Valley Bank', number: '1903551200911', verified: true },
  { id: 'r3', name: 'Pacific Power & Electric Co.', bank: 'Bank of America', number: '1180029188410', verified: true },
];

// Fixed timestamps keep server and client renders identical.
const SEED_TX: Transaction[] = [
  {
    id: 't2',
    ref: 'FT26101655102',
    accountId: 'acc_main',
    recipient: SEED_RECIPIENTS[1],
    amount: 45_000,
    note: 'Oct 2026 Cloud Infrastructure Services',
    status: 'succeeded',
    createdAt: Date.UTC(2026, 9, 16, 2, 42),
  },
  {
    id: 't1',
    ref: 'FT26101511240',
    accountId: 'acc_main',
    recipient: SEED_RECIPIENTS[2],
    amount: 18_250,
    note: 'HQ Corporate Utility Billing Sep 2026',
    status: 'succeeded',
    createdAt: Date.UTC(2026, 9, 15, 9, 18),
  },
];

interface BankState {
  accounts: Account[];
  recipients: Recipient[];
  transactions: Transaction[];
  lock: GuardLock | null;
  guardOnline: boolean;

  recordTransfer: (input: Omit<Transaction, 'id' | 'ref' | 'createdAt'>) => Transaction;
  setLock: (lock: GuardLock | null) => void;
  setGuardOnline: (online: boolean) => void;
}

export const useBank = create<BankState>((set) => ({
  accounts: SEED_ACCOUNTS,
  recipients: SEED_RECIPIENTS,
  transactions: SEED_TX,
  lock: null,
  guardOnline: false,

  recordTransfer: (input) => {
    const tx: Transaction = {
      ...input,
      id: `t_${Date.now()}`,
      ref: `FT2610${Math.floor(1_000_000 + Math.random() * 9_000_000)}`,
      createdAt: Date.now(),
    };
    set((s) => ({
      transactions: [tx, ...s.transactions],
      accounts:
        tx.status === 'succeeded'
          ? s.accounts.map((a) => (a.id === tx.accountId ? { ...a, balance: a.balance - tx.amount } : a))
          : s.accounts,
    }));
    return tx;
  },

  setLock: (lock) => set({ lock }),
  setGuardOnline: (guardOnline) => set({ guardOnline }),
}));
