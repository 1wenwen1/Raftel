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
        ['#4E79A7', '#F28E2B', '#E15759', '#76B7B2'])
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


SET_STYLES = {
    "set1": {"color": "#4E79A7", "marker": "o", "linestyle": "-",
             "label": "S1: TEE leader, totaltee=f+1"},
    "set2": {"color": "#F28E2B", "marker": "s", "linestyle": "-",
             "label": "S2: TEE leader, totaltee=f"},
    "set3": {"color": "#E15759", "marker": "^", "linestyle": "--",
             "label": "S3: non-TEE leader, totaltee=f+1"},
    "set4": {"color": "#76B7B2", "marker": "D", "linestyle": "--",
             "label": "S4: non-TEE leader, totaltee=f"},
}
FAULT_ORDER = [1, 2, 4, 8, 16, 32]


def parse_stats(stats_file: Path) -> dict:
    """Parse stats.txt into {set_name: {fault: (thr, lat)}}."""
    data = {}
    pattern = re.compile(r"^(set\d)_f(\d+),\s*([\d.]+),\s*([\d.]+)")
    with open(stats_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = pattern.match(line)
            if not m:
                continue
            set_name = m.group(1)
            fault = int(m.group(2))
            thr = float(m.group(3))
            lat = float(m.group(4))
            data.setdefault(set_name, {})[fault] = (thr, lat)
    return data


def plot_fig4(stats_file: Path, out_pdf: Path) -> None:
    _apply_style()
    data = parse_stats(stats_file)
    if not data:
        print(f"WARNING: no data parsed from {stats_file}")
        return

    fig, (ax_thr, ax_lat) = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)

    for set_name in ["set1", "set2", "set3", "set4"]:
        if set_name not in data:
            continue
        style = SET_STYLES[set_name]
        fault_map = data[set_name]
        faults = sorted(f for f in fault_map if f in FAULT_ORDER)
        x = faults
        thr = [fault_map[f][0] for f in faults]
        lat = [fault_map[f][1] for f in faults]

        kw = {k: v for k, v in style.items() if k != "label"}
        ax_thr.plot(x, thr, label=style["label"], **kw)
        ax_lat.plot(x, lat, label=style["label"], **kw)

    for ax, ylabel, title in [
        (ax_thr, "Throughput (kTPS)", "(a) Throughput"),
        (ax_lat, "Latency (ms)", "(b) Latency"),
    ]:
        ax.set_xlabel("Number of faults (f)")
        ax.set_ylabel(ylabel)
        ax.set_title(title, pad=6)
        ax.set_xticks(FAULT_ORDER)
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
        repo / "experiments_reproduction" / "experiment2" / "stats.txt",
    ))
    if not stats_file.exists():
        print(f"ERROR: stats file not found: {stats_file}", file=sys.stderr)
        sys.exit(1)

    run_dir = os.environ.get("AE_RUN_DIR")
    out_pdf = (Path(run_dir) / "figures" / "fig4.pdf") if run_dir else (
        repo / "experiments_reproduction" / "experiment2" / "results" / "fig4.pdf")

    plot_fig4(stats_file, out_pdf)

    canonical = repo / "experiments_reproduction" / "experiment2" / "results" / "fig4.pdf"
    if out_pdf != canonical:
        canonical.parent.mkdir(parents=True, exist_ok=True)
        import shutil; shutil.copy2(out_pdf, canonical)
        print(f"Copied: {canonical}")


if __name__ == "__main__":
    main()
