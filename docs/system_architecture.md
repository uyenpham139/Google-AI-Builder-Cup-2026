# ECHO-32 System Architecture

This document describes the current architecture of the **ECHO** project after being upgraded to meet Real-time High-Frequency Trading (HFT) standards.

## 1. Multi-Agent Orchestration

The system utilizes a **Supervisor-Worker** model, where the `SupervisorAgent` acts as the orchestrator coordinating 3 sub-agents running in parallel. The key design principle is that the Supervisor enforces an **extremely strict SLA (Service Level Agreement) of < 800ms**. Any agent that exceeds this timeframe is immediately cancelled to guarantee that the entire system never hangs.

```mermaid
graph TD
    Input[Audio PCM + Transcript] --> SA(Supervisor Agent)
    
    SA -- asyncio.wait(timeout=0.75) --> AW[Acoustic Watch Agent]
    SA -- asyncio.wait(timeout=0.75) --> CI[Coercion Intent Agent]
    SA -- asyncio.wait(timeout=0.75) --> DoA[DoA Violation Agent]
    
    AW -.->|Acoustic Score| SA
    CI -.->|Coercion Score| SA
    DoA -.->|DoA Score| SA
    
    SA --> Math[Risk = 0.45A + 0.35C + 0.20D]
    Math --> |> 0.85| Trigger[Trigger SecOps Lock & Barge-in]
    Math --> |< 0.85| Pass[Normal State]
    
    style SA fill:#f9f,stroke:#333,stroke-width:2px
    style AW fill:#bbf,stroke:#333
    style CI fill:#bbf,stroke:#333
    style DoA fill:#bbf,stroke:#333
    style Trigger fill:#f99,stroke:#333,stroke-width:2px
```

## 2. Acoustic Watch Agent: HFT Streaming Architecture

To process real-time audio at a **High-Frequency** standard, the `AcousticWatchAgent` does not use standard HTTP Requests. Instead, it employs a **Persistent Daemon** architecture combined with **In-Memory RAM Queues**.

```mermaid
sequenceDiagram
    participant Main as Supervisor (Main Thread)
    participant Queue as asyncio.Queue (RAM)
    participant Daemon as WebSocket Worker (Background)
    participant Google as Gemini Live API (Cloud)

    Main->>Daemon: Initialize (Pre-warm before meeting)
    Daemon->>Google: Establish WebSocket Connection (Keep-alive)
    
    Note over Main,Google: --- During Active Call ---
    
    Main->>Queue: Push Audio Chunk (pcm_bytes)
    Queue-->>Daemon: Pop()
    Daemon->>Google: Stream Data over WS
    Google-->>Daemon: Return Result (Stream)
    Daemon->>Queue: Push Result
    Queue-->>Main: Retrieve Result (< 300ms)
    
    Note over Main,Google: --- Network Failure / Latency Scenario ---
    
    Main->>Queue: Push Audio Chunk
    Main->>Main: Exceeds 0.7s (Timeout)
    Main->>Main: Fallback: Switch to Mathematical Heuristics (Zero-crossings & Energy)
    Main-->>Main: Return Heuristic Score! (Guaranteed < 800ms)
```

## 3. Key Architectural Features (NFRs)

1. **True Asynchronous:** Completely eliminates Blocking I/O by utilizing `aio.models` for the Coercion Agent. The Python Event Loop is 100% liberated.
2. **Network Fault Tolerance:** The Hybrid AI architecture allows the system to fallback to Heuristics (Digital Signal Processing algorithms that run locally without a network) if the LLM Cloud servers are congested.
3. **Persistent WebSocket:** Saves ~1 second of network overhead for every audio chunk by completely avoiding repetitive SSL/TLS Handshakes.

## 4. False-Positive Mitigation & Human-in-the-Loop (ECHO-33)

To prevent legitimate business conversations from triggering accidental meeting locks or voice barge-in interruptions:

1. **Contextual Cross-Validation (DoA Whitelist Attenuation):**
   - If an isolated Coercion urgency spike occurs ($C \ge 0.90$), but the beneficiary is in the verified ERP Whitelist ($D = 0.0$) and the voice acoustic is natural ($A < 0.30$), the Supervisor applies **Contextual Attenuation**. The risk is capped at `WARNING` (0.65) rather than escalating straight to `CRITICAL` (0.95).
2. **Codec/VoIP Noise Filtering (Acoustic Attenuation):**
   - Isolated acoustic glitches caused by VoIP compression or packet loss ($A \ge 0.90$) with zero coercion ($C < 0.20$) and compliant DoA ($D = 0.0$) are downgraded to `WARNING` to prevent erroneous locks on poor microphone setups.
3. **Temporal Multi-turn Smoothing:**
   - In live call streams (`/ws/call`), single isolated urgency signals trigger a `PROVISIONAL_ALERT`. Critical lockdown actions require either explicit malicious tactics (`BYPASS_FOUR_EYES`, `FORCED_SECRECY`) or multi-turn consecutive confirmation ($\ge 2$ turns).
4. **Human-in-the-Loop Override & Feedback:**
   - **REST API:** `POST /api/alerts/{session_id}/dismiss` allows SecOps operators to unlock an enforced session, suppress subsequent alarms, and log the feedback audit record for continuous model tuning.
   - **WebSocket Action:** Supports `{ "type": "dismiss_alert", "reason": "..." }` directly from the client.

