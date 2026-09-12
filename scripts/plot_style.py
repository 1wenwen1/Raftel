import os
import matplotlib as mpl
from cycler import cycler
from matplotlib.ticker import ScalarFormatter


def set_mpl_defaults() -> None:
    """Apply consistent, publication-friendly Matplotlib defaults.

    - Embed TrueType fonts (avoid Type 3)
    - Use Matplotlib's bundled DejaVu Sans font
    - Set color-blind-friendly palette and line/legend sizes
    """
    # Font embedding for vector outputs
    mpl.rcParams['pdf.fonttype'] = 42
    mpl.rcParams['ps.fonttype'] = 42

    # Bundled with Matplotlib, so report generation stays quiet and portable.
    mpl.rcParams['font.family'] = 'DejaVu Sans'

    # Color-blind friendly cycle
    mpl.rcParams['axes.prop_cycle'] = cycler(
        'color', ['#4E79A7', '#F28E2B', '#E15759', '#76B7B2']
    )

    mpl.rcParams['hatch.linewidth'] = 1.2


    # Sizes and lines
    mpl.rcParams.update({
        'font.size': 36,
        'axes.linewidth': 1.2,
        'axes.labelsize': 28,
        'xtick.labelsize': 20,
        'ytick.labelsize': 20,
        'legend.fontsize': 23,
        'lines.linewidth': 3,
        'lines.markersize': 9,
    })


def get_series_styles():
    linestyles = ['-', '--', '-.', ':']
    markers = ['o', 's', '^', 'd', 'x']
    styles = []
    for ls in linestyles:
        for mk in markers:
            styles.append((ls, mk))
    return styles


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def setup_grid(ax, major_alpha: float = 0.6, minor_alpha: float = 0.3) -> None:
    """Enable minor ticks and apply consistent grid styling."""
    ax.minorticks_on()
    ax.grid(which='major', alpha=major_alpha, linestyle='-', linewidth=0.8)
    ax.grid(which='minor', alpha=minor_alpha, linestyle=':', linewidth=0.5)


def apply_scalar_formatter(ax) -> None:
    ax.yaxis.set_major_formatter(ScalarFormatter(useMathText=True))


def save_all(fig, basename: str, folder: str = 'png', dpi: int = 300) -> None:
    """Save figure to pdf/eps/png under the given folder, ensuring it exists."""
    ensure_dir(folder)
    prefix = os.path.join(folder, basename)
    fig.savefig(f"{prefix}.pdf", format='pdf', dpi=dpi, bbox_inches="tight")
    fig.savefig(f"{prefix}.eps", format='eps', dpi=dpi, bbox_inches="tight")
    fig.savefig(f"{prefix}.png", format='png', dpi=dpi, bbox_inches="tight")


def add_ylim_padding(ax, top_ratio: float = 0.12, bottom_ratio: float = 0.06) -> None:
    """Add dynamic padding to y-limits to reduce overlap with legends/markers.

    - Scans line plots and bars to determine current y-range
    - Expands top by top_ratio and bottom by bottom_ratio
    """
    import math

    ys = []
    # Lines
    for line in ax.get_lines():
        y = line.get_ydata()
        if y is None:
            continue
        for v in y:
            if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
                continue
            ys.append(float(v))
    # Bars/patches
    for p in getattr(ax, 'patches', []):
        try:
            y0 = p.get_y()
            h = p.get_height()
            ys.append(float(y0))
            ys.append(float(y0 + h))
        except Exception:
            continue

    if not ys:
        return
    y_min = min(ys)
    y_max = max(ys)
    if y_max == y_min:
        pad = y_max * 0.1 if y_max != 0 else 1.0
        ax.set_ylim(y_min - pad, y_max + pad)
        return
    span = y_max - y_min
    ax.set_ylim(y_min - span * bottom_ratio, y_max + span * top_ratio)
