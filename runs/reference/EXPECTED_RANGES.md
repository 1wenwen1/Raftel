# Expected Ranges for PASS/WARN/FAIL Judgment

These reference values come from approximate reads of the paper PDF figures.
Replace with author-provided exact values when available.

## Criteria

| Verdict | Absolute deviation | Ordering |
|---|---|---|
| PASS | ≤ 40% from reference | matches paper ordering |
| WARN | 40–60% from reference | matches paper ordering |
| FAIL | > 60% from reference | OR ordering violated |

## Required Orderings

**Fig 3 throughput:** Achilles ≥ Chained ≥ Raftel > Hotstuff ≈ Raftel-Worst

**Fig 3 latency:** Raftel ≤ Chained < Basic-Damysus < Hotstuff ≈ Raftel-Worst

**Fig 4 throughput:** S1 > S2 ≥ S3 > S4

**Fig 4 latency:** S1 ≤ S2 ≤ S3 ≤ S4

**Fig 6 peak throughput:** Achilles ≥ Chained ≥ Raftel > Hotstuff

## Paper-Exact Values (from paper text)

- Fig 4 S1 at f=32: **31.5 kTPS** (§7.1)
- Fig 6 peak: Achilles=**95 TPS**, Chained=**92 TPS**, Raftel=**84 TPS**, Hotstuff=**44 TPS** (§7.6)

Note: Fig 6 reference CSV stores values in kTPS (divide TPS by 1000).
