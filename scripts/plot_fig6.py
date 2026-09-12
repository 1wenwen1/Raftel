#!/usr/bin/env python3
"""Plot Figure 6 (Redis WAN throughput-latency curve).

Input:  experiments_reproduction/experiment3/stats.txt
        (CSV format: protocol, load_clients, successful_repeats, metrics...)
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
    from cycler import cycler
except ImportError:
    print("ERROR: matplotlib required — pip install matplotlib", file=sys.stderr)
    sys.exit(1)


def _apply_style():
    import matplotlib as mpl
    mpl.rcParams['pdf.fonttype'] = 42
    mpl.rcParams['ps.fonttype'] = 42
    mpl.rcParams['font.family'] = 'serif'
    mpl.rcParams['font.serif'] = ['Times New Roman', 'Palatino', 'CMU Serif', 'DejaVu Serif']
    mpl.rcParams['axes.prop_cycle'] = cycler('color',
        ['#4E79A7', '#F28E2B', '#59A14F', '#E15759', '#76B7B2'])
    mpl.rcParams.update({
        'font.size': 11,
        'axes.linewidth': 1.2,
        'axes.labelsize': 11,
        'xtick.labelsize': 10,
        'ytick.labelsize': 10,
        'legend.fontsize': 9,
        'lines.linewidth': 2,
        'lines.markersize': 6,
    })


PROTOCOL_STYLES = {
    "Raftel":        {"color": "#4E79A7", "marker": "o", "linestyle": "-"},
    "Chained":       {"color": "#F28E2B", "marker": "s", "linestyle": "-"},
    "Achilles":      {"color": "#59A14F", "marker": "^", "linestyle": "-"},
    "Hotstuff":      {"color": "#E15759", "marker": "D", "linestyle": "-"},
    "Basic-Damysus": {"color": "#76B7B2", "marker": "v", "linestyle": "-"},
}

PROTOCOL_ORDER = ["Achilles", "Chained", "Raftel", "Basic-Damysus", "Hotstuff"]


def parse_stats(stats_file: Path) -> dict:
    """Parse stats CSV (from summarize_e2e.py aggregate) into protocol -> [(thr_tps, lat_ms)]."""
    data = {}
    with open(stats_file, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            protocol = row.get("protocol", "").strip()
            if not protocol or protocol == "protocol":
                continue
            try:
                thr_tps = float(row["e2e_throughput_ktps"]) * 1000.0
                lat_ms = float(row["e2e_latency_avg_ms"])
            except (KeyError, ValueError):
                continue
            data.setdefault(protocol, []).append((thr_tps, lat_ms))
    # sort by throughput for clean curves
    for p in data:
        data[p].sort(key=lambda pt: pt[0])
    return data


def plot_fig6(stats_file: Path, out_pdf: Path) -> None:
    _apply_style()
    data = parse_stats(stats_file)
    if not data:
        print(f"WARNING: no data parsed from {stats_file}")
        return

    fig, ax = plt.subplots(figsize=(6, 4), constrained_layout=True)

    for protocol in PROTOCOL_ORDER:
        if protocol not in data:
            continue
        style = PROTOCOL_STYLES.get(protocol, {"color": "gray", "marker": "x", "linestyle": "-"})
        points = data[protocol]
        thr = [pt[0] for pt in points]
        lat = [pt[1] for pt in points]
        ax.plot(thr, lat, label=protocol, **style)

    # also plot any protocol not in PROTOCOL_ORDER
    for protocol, points in sorted(data.items()):
        if protocol in PROTOCOL_ORDER:
            continue
        style = PROTOCOL_STYLES.get(protocol, {"color": "gray", "marker": "x", "linestyle": "-"})
        thr = [pt[0] for pt in points]
        lat = [pt[1] for pt in points]
        ax.plot(thr, lat, label=protocol, **style)

    ax.set_xlabel("Throughput (TPS)")
    ax.set_ylabel("Average latency (ms)")
    ax.set_title("Redis KV end-to-end (WAN, f=8)", pad=6)
    ax.minorticks_on()
    ax.grid(which='major', alpha=0.5, linestyle='-', linewidth=0.7)
    ax.grid(which='minor', alpha=0.25, linestyle=':', linewidth=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(frameon=False, ncol=1)

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_pdf, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_pdf}")


def main():
    repo = Path(__file__).resolve().parent.parent
    stats_file = Path(os.environ.get(
        "AE_STATS_FILE",
        repo / "experiments_reproduction" / "experiment3" / "stats.txt",
    ))
    if not stats_file.exists():
        print(f"ERROR: stats file not found: {stats_file}", file=sys.stderr)
        sys.exit(1)

    run_dir = os.environ.get("AE_RUN_DIR")
    out_pdf = (Path(run_dir) / "figures" / "fig6.pdf") if run_dir else (
        repo / "experiments_reproduction" / "experiment3" / "results" / "fig6.pdf")

    plot_fig6(stats_file, out_pdf)

    canonical = repo / "experiments_reproduction" / "experiment3" / "results" / "fig6.pdf"
    if out_pdf != canonical:
        canonical.parent.mkdir(parents=True, exist_ok=True)
        import shutil; shutil.copy2(out_pdf, canonical)
        print(f"Copied: {canonical}")


if __name__ == "__main__":
    main()
