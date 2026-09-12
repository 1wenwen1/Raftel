# Reference data and acceptance limits

`original/` contains byte-for-byte CSV files from the author's `raftel.zip`.
These are reference measurements, never newly executed AE results.
The validated adapter reads these source files directly. It maps paper protocol
names to CLI names, reproduces Figure 4's six ordinal positions on the shared
`f={1,2,4,8,16,32}` axis, and treats Figure 6 source rows as curve points rather
than offered-load identifiers because all source thread counts are 1.

The report applies per-configuration absolute deviations: ≤40% PASS, >40–60%
WARN, >60% FAIL. Material ordering reversals beyond 6% fail separately. Missing
measurements, simulation runs, and unverified hardware cannot receive PASS.
These thresholds are artifact-specific acceptance criteria, not EuroSys badge rules.

Source-data handling:

- Fig4 S2 has two source rows labelled 1 and none labelled 2. The original
  script puts its six sorted values on six shared fault positions, effectively
  placing the second S2 row at f=2. The adapter follows those positions while
  retaining the byte-for-byte source CSV.
- Fig4 uses a 6% ordering tolerance because the paper describes S2 and S3 as
  close and the source curves include a 5.24% latency reversal at `f=1`.
- Fig6 CSV and original script select rows labelled LAN, while the AE experiment
  applies the paper's 50 ms WAN setup. The original script plots throughput
  directly against latency, so the malformed source thread identifiers do not
  define the curve geometry.
- Fig6 textual peaks (Achilles 95, Chained-Raftel 92, Raftel 84, HotStuff 44 TPS)
  differ from maxima in the supplied CSV. The explicit paper values define the
  peak acceptance check; the source CSV remains available for visual comparison.

Plot the original data using `--input runs/reference/original/<file>.csv`.
For a measured run, plot only `runs/<RUN_ID>/raw/experimentN/stats.txt`.
Historical reports use the reference snapshot archived inside their run directory.
