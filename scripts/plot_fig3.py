#!/usr/bin/env python3
"""Plot Figure 3 (WAN scalability): throughput and latency vs. number of faults.

Input:  experiments_reproduction/experiment1/stats.txt
        (format: label, thr_mean, lat_mean  — one line per protocol/fault combo)
Output: runs/RUN_ID/figures/fig3.pdf  (or passed via AE_RUN_DIR env var)
        experiments_reproduction/experiment1/results/fig3.pdf
"""

import csv
import os
import re
import sys
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as ticker
except ImportError:
    print("ERROR: matplotlib is required — pip install matplotlib", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Style: publication-quality, matches paper figure conventions
# ---------------------------------------------------------------------------
PROTOCOL_STYLES = {
    "Raftel":        {"color": "#1a6faf", "marker": "o", "linestyle": "-",  "zorder": 4},
    "Raftel-Worst":  {"color": "#1a6faf", "marker": "o", "linestyle": "--", "zorder": 3},
    "Chained":       {"color": "#e07b00", "marker": "s", "linestyle": "-",  "zorder": 3},
    "Achilles":      {"color": "#2ca02c", "marker": "^", "linestyle": "-",  "zorder": 3},
    "Hotstuff":      {"color": "#d62728", "marker": "D", "linestyle": "-",  "zorder": 3},
    "Basic-Damysus": {"color": "#9467bd", "marker": "v", "linestyle": "-",  "zorder": 3},
}

FAULT_ORDER = [1, 2, 4, 8, 16, 32]


def parse_stats(stats_file: Path) -> dict:
    """Parse stats.txt into {protocol: {fault: (thr, lat)}}."""
    data = {}
    pattern = re.compile(r"^(.+?)_f(\d+),\s*([\d.]+),\s*([\d.]+)")
    with open(stats_file) as f:
        for line in f:
            m = pattern.match(line.strip())
            if not m:
                continue
            protocol = m.group(1)
            fault = int(m.group(2))
            thr = float(m.group(3))
            lat = float(m.group(4))
            data.setdefault(protocol, {})[fault] = (thr, lat)
    return data


def plot_fig3(stats_file: Path, out_pdf: Path) -> None:
    data = parse_stats(stats_file)
    if not data:
        print(f"WARNING: no data parsed from {stats_file}")
        return

    fig, (ax_thr, ax_lat) = plt.subplots(
        1, 2, figsize=(10, 4), constrained_layout=True
    )

    for protocol, fault_map in sorted(data.items()):
        style = PROTOCOL_STYLES.get(protocol, {"color": "gray", "marker": "x", "linestyle": "-", "zorder": 2})
        faults = sorted(f for f in fault_map if f in FAULT_ORDER)
        if not faults:
            continue
        x = faults
        thr = [fault_map[f][0] for f in faults]
        lat = [fault_map[f][1] for f in faults]

        ax_thr.plot(x, thr, label=protocol, **style, linewidth=1.5, markersize=5)
        ax_lat.plot(x, lat, label=protocol, **style, linewidth=1.5, markersize=5)

    for ax, ylabel, title in [
        (ax_thr, "Throughput (kTPS)", "(a) Throughput"),
        (ax_lat, "Latency (ms)", "(b) Latency"),
    ]:
        ax.set_xlabel("Number of faults (f)", fontsize=10)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.set_title(title, fontsize=10, pad=4)
        ax.set_xticks(FAULT_ORDER)
        ax.tick_params(labelsize=9)
        ax.grid(axis="y", linestyle=":", linewidth=0.5, alpha=0.7)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.legend(fontsize=8, framealpha=0.8, edgecolor="none")

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_pdf, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_pdf}")


def main():
    repo = Path(__file__).resolve().parent.parent
    stats_file = repo / "experiments_reproduction" / "experiment1" / "stats.txt"
    if not stats_file.exists():
        print(f"ERROR: stats file not found: {stats_file}", file=sys.stderr)
        sys.exit(1)

    run_dir = os.environ.get("AE_RUN_DIR")
    if run_dir:
        out_pdf = Path(run_dir) / "figures" / "fig3.pdf"
    else:
        out_pdf = repo / "experiments_reproduction" / "experiment1" / "results" / "fig3.pdf"

    plot_fig3(stats_file, out_pdf)

    # Also copy to canonical results path
    canonical = repo / "experiments_reproduction" / "experiment1" / "results" / "fig3.pdf"
    if out_pdf != canonical:
        canonical.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(out_pdf, canonical)
        print(f"Copied: {canonical}")


if __name__ == "__main__":
    main()
