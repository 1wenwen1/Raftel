#!/usr/bin/env python3
"""Plot Figure 4 (LAN leader/quorum combos): throughput and latency for 4 Raftel variants.

Input:  experiments_reproduction/experiment2/stats.txt
Output: runs/RUN_ID/figures/fig4.pdf
"""

import os
import re
import sys
from pathlib import Path

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    print("ERROR: matplotlib required — pip install matplotlib", file=sys.stderr)
    sys.exit(1)

SET_STYLES = {
    "set1": {"color": "#1a6faf", "marker": "o", "linestyle": "-",  "label": "S1 (TEE leader, f+1 TEE)"},
    "set2": {"color": "#e07b00", "marker": "s", "linestyle": "-",  "label": "S2 (TEE leader, f TEE)"},
    "set3": {"color": "#2ca02c", "marker": "^", "linestyle": "--", "label": "S3 (non-TEE leader, f+1 TEE)"},
    "set4": {"color": "#d62728", "marker": "D", "linestyle": "--", "label": "S4 (non-TEE leader, f TEE)"},
}
FAULT_ORDER = [1, 2, 4, 8, 16, 32]


def parse_stats(stats_file: Path) -> dict:
    """Parse stats.txt into {set_name: {fault: (thr, lat)}}."""
    data = {}
    pattern = re.compile(r"^(set\d)_f(\d+),\s*([\d.]+),\s*([\d.]+)")
    with open(stats_file) as f:
        for line in f:
            m = pattern.match(line.strip())
            if not m:
                continue
            set_name = m.group(1)
            fault = int(m.group(2))
            thr = float(m.group(3))
            lat = float(m.group(4))
            data.setdefault(set_name, {})[fault] = (thr, lat)
    return data


def plot_fig4(stats_file: Path, out_pdf: Path) -> None:
    data = parse_stats(stats_file)
    if not data:
        print(f"WARNING: no data parsed from {stats_file}")
        return

    fig, (ax_thr, ax_lat) = plt.subplots(
        1, 2, figsize=(10, 4), constrained_layout=True
    )

    for set_name in ["set1", "set2", "set3", "set4"]:
        if set_name not in data:
            continue
        style = SET_STYLES[set_name]
        fault_map = data[set_name]
        faults = sorted(f for f in fault_map if f in FAULT_ORDER)
        x = faults
        thr = [fault_map[f][0] for f in faults]
        lat = [fault_map[f][1] for f in faults]

        kwargs = {k: v for k, v in style.items() if k not in ("label",)}
        ax_thr.plot(x, thr, label=style["label"], **kwargs, linewidth=1.5, markersize=5)
        ax_lat.plot(x, lat, label=style["label"], **kwargs, linewidth=1.5, markersize=5)

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
    stats_file = repo / "experiments_reproduction" / "experiment2" / "stats.txt"
    if not stats_file.exists():
        print(f"ERROR: stats file not found: {stats_file}", file=sys.stderr)
        sys.exit(1)

    run_dir = os.environ.get("AE_RUN_DIR")
    if run_dir:
        out_pdf = Path(run_dir) / "figures" / "fig4.pdf"
    else:
        out_pdf = repo / "experiments_reproduction" / "experiment2" / "results" / "fig4.pdf"

    plot_fig4(stats_file, out_pdf)

    canonical = repo / "experiments_reproduction" / "experiment2" / "results" / "fig4.pdf"
    if out_pdf != canonical:
        canonical.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy2(out_pdf, canonical)
        print(f"Copied: {canonical}")


if __name__ == "__main__":
    main()
