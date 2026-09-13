#!/usr/bin/env python3
"""Plot paper fig3; accepts original CSV or run-local AE statistics."""
from paper_plot import main, plot


def plot_fig3(stats_file, out_pdf):
    return plot("fig3", stats_file, out_pdf)


if __name__ == "__main__":
    main("fig3")
