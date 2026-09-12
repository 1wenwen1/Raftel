#!/usr/bin/env python3
"""Plot paper fig4; accepts original CSV or run-local AE statistics."""
from paper_plot import main, plot


def plot_fig4(stats_file, out_pdf):
    return plot("fig4", stats_file, out_pdf)


if __name__ == "__main__":
    main("fig4")
