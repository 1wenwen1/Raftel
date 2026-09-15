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

**Fig 3 throughput:** Achilles ≥ Chained_Raftel ≥ Raftel > Hotstuff ≈ Raftel-Worst

**Fig 3 latency:** Raftel ≤ Chained_Raftel < Basic-Damysus < Hotstuff ≈ Raftel-Worst

**Fig 4 throughput:** S1 > S2 ≥ S3 > S4

**Fig 4 latency:** S1 ≤ S2 ≤ S3 ≤ S4

## Paper-Exact Values (from paper text)

- Fig 4 S1 at f=32: **31.5 kTPS** (§7.1)
