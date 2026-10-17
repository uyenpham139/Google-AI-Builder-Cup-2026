COERCION_INTENT_PROMPT = """
You are a cybersecurity expert specializing in CEO/CFO Fraud and Social Engineering detection.
Your task is to analyze the following conversation segment and do two things:
1. Extract transaction details (amount, recipient, urgency level).
2. Evaluate whether the conversation contains psychological manipulation or coercion tactics.

The coercion tactics include:
- URGENCY_PRESSURE: Creating extreme time pressure (urgent, immediately, before 5 PM).
- FORCED_SECRECY: Requiring unusual secrecy (top secret, do not tell anyone, keep quiet).
- BYPASS_FOUR_EYES: Requesting to bypass standard control procedures (skip dual-signature, approve it yourself, no need to wait).
- AUTHORITY_INTIMIDATION: Using authority to threaten (demotion, firing, bear the consequences).

Scoring Rules (coercion_score):
- If any coercion tactic is clearly present, coercion_score >= 0.85
- If it is a normal business conversation with no signs of fraud, coercion_score < 0.20

CRITICAL FALSE-POSITIVE MITIGATION & SELF-REFLECTION:
- Distinguish legitimate business urgency from malicious coercion. Routine operational deadlines (e.g. paying regular invoices before 5 PM cut-off, standard payroll) without secrecy, intimidation, or bypass of approval rules MUST NOT be scored as fraud (score <= 0.30).
- Social engineering requires abnormal pressure: FORCED_SECRECY ("tell no one"), BYPASS_FOUR_EYES ("skip approval/sign yourself"), or AUTHORITY_INTIMIDATION ("or you will be fired").
- If the request is for normal business operations, do NOT assign a critical score (>= 0.85).

Conversation segment: "{text_segment}"
"""
