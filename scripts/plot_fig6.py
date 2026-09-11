#!/usr/bin/env python3
"""Plot Figure 6 (Redis WAN throughput-latency curve).

Input:  experiments_reproduction/experiment3/stats.txt
        (CSV format with columns: protocol, load_clients, successful_repeats, metrics...)
Output: runs/RUN_ID/figures/fig6.pdf
"""

import csv
import os
import sys
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    print("ERROR: matplotlib required — pip install matplotlib", file=sys.stderr)
    sys.exit(1)

PROTOCOL_STYLES = {
    "Raftel":        {"color": "#1a6faf", "marker": "o", "linestyle": "-"},
    "Chained":       {"color": "#e07b00", "marker": "s", "linestyle": "-"},
    "Achilles":      {"color": "#2ca02c", "marker": "^", "linestyle": "-"},
    "Hotstuff":      {"color": "#d62728", "marker": "D", "linestyle": "-"},
    "Basic-Damysus": {"color": "#9467bd", "marker": "v", "linestyle": "-"},
}


def parse_stats(stats_file: Path) -> dict:
    """Parse stats CSV (produced by summarize_e2e.py aggregate) into protocol -> sorted [(thr, lat)]."""
    data = {}
    with open(stats_file, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            protocol = row.get("protocol", "").strip()
            if not protocol:
                continue
            try:
                # throughput is in kTPS; convert to TPS to match paper axis
                thr_tps = float(row["e2e_throughput_ktps"]) * 1000.0
                lat_ms = float(row["e2e_latency_avg_ms"])
            except (KeyError, ValueError):
                continue
            data.setdefault(protocol, []).append((thr_tps, lat_ms))
    # sort each protocol's points by throughput for clean curves
    for p in data:
        data[p].sort(key=lambda pt: pt[0])
    return data


def plot_fig6(stats_file: Path, out_pdf: Path) -> None:
    data = parse_stats(stats_file)
    if not data:
        print(f"WARNING: no data parsed from {stats_file}")
        return

    fig, ax = plt.subplots(figsize=(6, 4), constrained_layout=True)

    for protocol, points in sorted(data.items()):
        style = PROTOCOL_STYLES.get(protocol, {"color": "gray", "marker": "x", "linestyle": "-"})
        thr = [pt[0] for pt in points]
        lat = [pt[1] for pt in points]
        ax.plot(thr, lat, label=protocol, **style, linewidth=1.5, markersize=5)

    ax.set_xlabel("Throughput (TPS)", fontsize=10)
    ax.set_ylabel("Average latency (ms)", fontsize=10)
    ax.set_title("Redis KV end-to-end (WAN)", fontsize=10, pad=4)
    ax.tick_params(labelsize=9)
    ax.grid(axis="both", linestyle=":", linewidth=0.5, alpha=0.7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(fontsize=8, framealpha=0.8, edgecolor="none")

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_pdf, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_pdf}")


def main():
    repo = Path(__file__).resolve().parent.parent
    stats_file = repo / "experiments_reproduction" / "experiment3" / "stats.txt"
    if not stats_file.exists():
        print(f"ERROR: stats file not found: {stats_file}", file=sys.stderr)
        sys.exit(1)

    run_dir = os.environ.get("AE_RUN_DIR")
    if run_dir:
        out_pdf = Path(run_dir) / "figures" / "fig6.pdf"
    else:
        out_pdf = repo / "experiments_reproduction" / "experiment3" / "results" / "fig6.pdf"

    plot_fig6(stats_file, out_pdf)

    canonical = repo / "experiments_reproduction" / "experiment3" / "results" / "fig6.pdf"
    if out_pdf != canonical:
        canonical.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(out_pdf, canonical)
        print(f"Copied: {canonical}")


if __name__ == "__main__":
    main()
