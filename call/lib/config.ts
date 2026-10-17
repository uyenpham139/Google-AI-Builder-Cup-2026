export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
export const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL ?? (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000').replace(/^http/, 'ws');

export const CALLER = { name: 'Robert Higgins', role: 'Chief Executive Officer', initials: 'RH' };
export const SELF = { name: 'Alex Chen', role: 'Treasury Controller', initials: 'AC' };

export interface Scenario {
  id: string;
  label: string;
  lines: string[];
}

export const SCENARIOS: Scenario[] = [
  {
    id: 'scam',
    label: 'CEO Impersonation (Emergency Wire)',
    lines: [
      "Alex, this is Robert Higgins. I am in transit at the Singapore terminal right now.",
      "You need to wire twenty-five point six million dollars immediately to the Standard Chartered offshore escrow account I just sent, before three PM.",
      "This M&A transaction is strictly confidential. Skip the CFO dual-signature requirement—I take full executive liability. Execute the transfer now."
    ],
  },
  {
    id: 'urgent-legit',
    label: 'Urgent Approved Vendor Wire',
    lines: [
      "Hi Alex, Robert here.",
      "Please process the expedited payment for twenty-five thousand dollars to our verified partner before five PM today.",
      "The paperwork has already been signed in the treasury queue. Follow standard operating procedure as usual."
    ],
  },
  {
    id: 'normal',
    label: 'Internal Liquidity Review',
    lines: [
      "Hi Alex, just checking in on the quarterly liquidity review.",
      "Please ensure the consolidated cash-flow statement is prepared for tomorrow's audit committee briefing."
    ],
  },
];

export const BARGE_IN_MESSAGE =
  'Security alert from Echo. High-risk financial fraud indicators detected. Wire transfer portal locked. Verify caller through secondary out-of-band channel immediately.';

