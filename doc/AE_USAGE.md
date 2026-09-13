# Raftel AE Usage

This document describes the two reviewer execution profiles. The public command
exposes only `sim` and `full`.

## Reviewer Commands

Run these commands from the prepared runner:

```bash
./ae run all --mode sim
./ae run all --mode full
```

The positional target after `run` selects the experiment:

| Target | Experiment |
|---|---|
| `fig3` | WAN scalability across six protocols |
| `fig4` | LAN TEE configuration comparison |
| `fig6` | Redis WAN end-to-end workload |
| `all` | Run `fig3`, `fig4`, and `fig6` in that order |

Every run creates a timestamped directory under `runs/`, archives raw output,
records the source and build provenance, generates figures, and writes
`index.html`. A failed experiment or missing data keeps the run failed; the
report is not allowed to turn an incomplete run into a pass.

## `sim` Mode

`sim` is the cost-saving, reviewer-visible pipeline profile.

- SGX build mode: `SIM`.
- Physical topology: seven hosts.
- Replica placement: up to 15 logical replicas per host on distinct ports,
  giving capacity for 105 logical replicas.
- Largest case: `f=32`, `n=3f+1=97` logical replicas.
- Figure 3 and Figure 4: all six fault points, `f={1,2,4,8,16,32}`.
- Figure 6: `f=8`, clients `{1,2,4,8,16,32}`, one repeat.
- Claim status: useful for checking orchestration, data collection, plotting,
  and trends; it is not hardware evidence and is not eligible for the full
  one-replica-per-VM paper claim.

On a prepared runner with no replica inventory, this mode provisions the seven
temporary replica hosts, initializes them, runs the experiments, and attempts
to release those temporary hosts whenever the run ends. The runner itself is
kept. Provider-side auto-release is also configured as a fallback.

## `full` Mode

`full` is the paper-topology profile.

- SGX build mode: `HW`.
- Replica placement: one physical SGX VM per replica; multiplexing is disabled.
- Figure 3 and Figure 4: up to 97 replica VMs at `f=32`.
- Figure 6: 25 replica VMs at `f=8`.
- Figure 6 uses three repeats.
- Claim status: eligible for the complete hardware reproduction criteria only
  when the hardware preflight and all experiment points pass.

The runner and replica traffic use the private VPC network. The report records
the number of physical hosts, logical replicas, SGX mode, and hardware
verification result in `manifest.json`.

On a prepared runner with no replica inventory, this mode provisions the
required 97 hosts for `fig3`, `fig4`, or `all`, or 25 hosts for a `fig6`-only
run. It follows the same initialize, verify, run, archive, and release lifecycle
as `sim`.

## Other Commands

```bash
./ae doctor                  # diagnose dependencies on an existing cluster
./ae report [RUN_ID]         # regenerate figures and HTML from archived data
./ae status [RUN_ID]         # inspect run status
./ae cloud check             # validate the prepared replica cluster
```
