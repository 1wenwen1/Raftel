#!/usr/bin/env python3
"""Generate a standalone HTML report from a run directory.

Usage: python3 gen_report.py <run_dir>

Reads:
  <run_dir>/manifest.json
  <run_dir>/figures/fig{3,4,6}.pdf  (converted to PNG for embedding)
  experiments_reproduction/experiment{1,2,3}/stats.txt
  runs/reference/fig{3,4,6}.csv
  <run_dir>/checksums.txt

Writes:
  <run_dir>/index.html  (self-contained, no external deps)
"""

import base64
import csv
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REFERENCE_DIR = REPO / "runs" / "reference"

# PASS/WARN/FAIL thresholds (relative deviation from reference)
PASS_THRESHOLD = 0.40
WARN_THRESHOLD = 0.60


def pdf_to_png(pdf_path: Path, out_png: Path) -> bool:
    """Convert PDF to PNG via pdftoppm or convert (ImageMagick)."""
    if shutil.which("pdftoppm"):
        subprocess.call(
            ["pdftoppm", "-r", "150", "-l", "1", "-png",
             str(pdf_path), str(out_png.with_suffix(""))],
        )
        candidate = out_png.with_suffix("").parent / (out_png.stem + "-1.png")
        if candidate.exists():
            candidate.rename(out_png)
            return True
    if shutil.which("convert"):
        rc = subprocess.call(
            ["convert", "-density", "150", f"{pdf_path}[0]", str(out_png)]
        )
        return rc == 0
    return False


def embed_image(path: Path) -> str:
    """Return a base64 data-URL for an image file."""
    suffix = path.suffix.lower()
    mime = {
        "png": "image/png", "jpg": "image/jpeg",
        "jpeg": "image/jpeg", "svg": "image/svg+xml",
    }.get(suffix[1:], "image/png")
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{data}"


def read_file_safe(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Reference data loading
# ---------------------------------------------------------------------------

def _load_reference_ranges(fig: str) -> dict:
    """Load reference CSV for *fig* and return a lookup dict.

    Returns:
        For fig3/fig4: {(protocol_or_set, str(faults)): {"thr": float, "lat": float}}
        For fig6:      {(protocol, str(load_clients)): {"thr": float, "lat": float}}
    """
    csv_path = REFERENCE_DIR / f"{fig}.csv"
    if not csv_path.exists():
        return {}
    result = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            # skip comment rows (lines starting with #)
            if not row:
                continue
            try:
                if fig == "fig3":
                    key = (row["protocol"], row["faults"])
                    result[key] = {
                        "thr": float(row["throughput_ktps"]),
                        "lat": float(row["latency_ms"]),
                    }
                elif fig == "fig4":
                    key = (row["set"], row["faults"])
                    result[key] = {
                        "thr": float(row["throughput_ktps"]),
                        "lat": float(row["latency_ms"]),
                    }
                elif fig == "fig6":
                    key = (row["protocol"], row["load_clients"])
                    result[key] = {
                        "thr": float(row["throughput_ktps"]),
                        "lat": float(row["latency_avg_ms"]),
                    }
            except (KeyError, ValueError):
                continue
    return result


def _verdict(measured: float, reference: float) -> str:
    """Return PASS / WARN / FAIL based on relative deviation."""
    if reference == 0:
        return "PASS" if measured == 0 else "WARN"
    dev = abs(measured - reference) / reference
    if dev <= PASS_THRESHOLD:
        return "PASS"
    if dev <= WARN_THRESHOLD:
        return "WARN"
    return "FAIL"


def _verdict_badge(v: str) -> str:
    colors = {"PASS": "#2a7a2a", "WARN": "#a06000", "FAIL": "#9a1c1c"}
    return (
        f'<span class="verdict" style="background:{colors.get(v,"#555")}">'
        f'{v}</span>'
    )


# ---------------------------------------------------------------------------
# Stats parsing
# ---------------------------------------------------------------------------

def _parse_stats_txt(stats_file: Path) -> list[dict]:
    """Parse stats.txt into a list of row dicts.

    Line format (experiment1/2):
        label, thr_view=X, lat_view=Y, e2e_reply_tps=Z, ...
    Line format (experiment3 — CSV):
        protocol,load_clients,successful_repeats,e2e_throughput_ktps,...
    """
    rows = []
    if not stats_file.exists():
        return rows
    text = stats_file.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Try CSV format (experiment3 summary)
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 4 and not "=" in line:
            rows.append({"_raw": line, "_parts": parts})
            continue
        # Key=value format (experiment1/2)
        row = {"_raw": line}
        for token in parts:
            if "=" in token:
                k, v = token.split("=", 1)
                row[k.strip()] = v.strip()
            elif not row.get("label"):
                row["label"] = token
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Per-figure comparison tables
# ---------------------------------------------------------------------------

def _fig3_table(ref: dict) -> str:
    stats_file = REPO / "experiments_reproduction" / "experiment1" / "stats.txt"
    rows = _parse_stats_txt(stats_file)
    if not rows:
        return "<p class='muted'>stats.txt not found — run experiment1 first.</p>"

    html = """
    <h3>Experiment parameters</h3>
    <table>
      <tr><th>Parameter</th><th>Value</th></tr>
      <tr><td>Protocols</td><td>Raftel, Chained, Achilles, Hotstuff, Basic-Damysus, Raftel-Worst</td></tr>
      <tr><td>Fault values (f)</td><td>1, 2, 4, 8, 16, 32</td></tr>
      <tr><td>Batch size</td><td>400 tx/block</td></tr>
      <tr><td>Payload</td><td>256 B</td></tr>
      <tr><td>Network</td><td>WAN — 50 ms one-way netem delay (100 ms RTT)</td></tr>
      <tr><td>SGX mode</td><td>HW</td></tr>
      <tr><td>Raftel totaltee</td><td>f+1 (Raftel-Best); totaltee=0 for Raftel-Worst</td></tr>
    </table>
    <h3>Paper claim</h3>
    <p class='claim'>§7.2: Raftel achieves throughput comparable to Chained and significantly better
    than Hotstuff, while its latency is lower than or equal to Chained and far below Hotstuff.
    Achilles leads in throughput because its smaller quorum (2f+1) requires fewer votes.</p>
    """

    if not ref:
        html += "<p class='muted warn'>Reference CSV not found — PASS/WARN/FAIL unavailable.</p>"
        return html

    html += """
    <h3>Results vs. reference</h3>
    <table>
      <tr><th>Config</th><th>Thr measured (kTPS)</th><th>Thr ref</th><th>Thr verdict</th>
          <th>Lat measured (ms)</th><th>Lat ref</th><th>Lat verdict</th></tr>
    """
    for row in rows:
        label = row.get("label", row.get("_raw", ""))
        thr = row.get("thr_view", "")
        lat = row.get("lat_view", "")
        # try to parse protocol/faults from label like "Raftel_f8"
        ref_thr = ref_lat = None
        parts = label.split("_f")
        if len(parts) == 2:
            protocol, faults = parts[0], parts[1]
            ref_row = ref.get((protocol, faults))
            if ref_row:
                ref_thr, ref_lat = ref_row["thr"], ref_row["lat"]
        try:
            thr_f = float(thr)
            thr_v = _verdict(thr_f, ref_thr) if ref_thr is not None else "—"
        except (ValueError, TypeError):
            thr_f, thr_v = None, "—"
        try:
            lat_f = float(lat)
            lat_v = _verdict(lat_f, ref_lat) if ref_lat is not None else "—"
        except (ValueError, TypeError):
            lat_f, lat_v = None, "—"
        thr_badge = _verdict_badge(thr_v) if thr_v != "—" else "—"
        lat_badge = _verdict_badge(lat_v) if lat_v != "—" else "—"
        html += (
            f"<tr><td>{label}</td>"
            f"<td>{thr or '—'}</td><td>{ref_thr or '—'}</td><td>{thr_badge}</td>"
            f"<td>{lat or '—'}</td><td>{ref_lat or '—'}</td><td>{lat_badge}</td></tr>\n"
        )
    html += "</table>"
    return html


def _fig4_table(ref: dict) -> str:
    stats_file = REPO / "experiments_reproduction" / "experiment2" / "stats.txt"
    rows = _parse_stats_txt(stats_file)
    if not rows:
        return "<p class='muted'>stats.txt not found — run experiment2 first.</p>"

    html = """
    <h3>Experiment parameters</h3>
    <table>
      <tr><th>Parameter</th><th>Value</th></tr>
      <tr><td>Sets</td><td>S1: TEE leader totaltee=f+1 · S2: TEE leader totaltee=f ·
          S3: non-TEE leader totaltee=f+1 · S4: non-TEE leader totaltee=f</td></tr>
      <tr><td>Fault values (f)</td><td>1, 2, 4, 8, 16, 32</td></tr>
      <tr><td>Batch size</td><td>400 tx/block</td></tr>
      <tr><td>Payload</td><td>256 B</td></tr>
      <tr><td>Network</td><td>LAN (no WAN delay)</td></tr>
      <tr><td>SGX mode</td><td>HW</td></tr>
    </table>
    <h3>Paper claim</h3>
    <p class='claim'>§7.3: TEE leadership and a full TEE quorum (S1) yield the highest throughput.
    Removing either degrades performance, with S1 &gt; S2 ≥ S3 &gt; S4 for throughput
    and S1 ≤ S2 ≤ S3 ≤ S4 for latency. S1 at f=32 achieves 31.5 kTPS.</p>
    """

    if not ref:
        html += "<p class='muted warn'>Reference CSV not found — PASS/WARN/FAIL unavailable.</p>"
        return html

    html += """
    <h3>Results vs. reference</h3>
    <table>
      <tr><th>Config</th><th>Thr measured (kTPS)</th><th>Thr ref</th><th>Thr verdict</th>
          <th>Lat measured (ms)</th><th>Lat ref</th><th>Lat verdict</th></tr>
    """
    for row in rows:
        label = row.get("label", row.get("_raw", ""))
        thr = row.get("thr_view", "")
        lat = row.get("lat_view", "")
        ref_thr = ref_lat = None
        # label like "set1_f8"
        parts = label.split("_f")
        if len(parts) == 2:
            set_name, faults = parts[0], parts[1]
            ref_row = ref.get((set_name, faults))
            if ref_row:
                ref_thr, ref_lat = ref_row["thr"], ref_row["lat"]
        try:
            thr_f = float(thr)
            thr_v = _verdict(thr_f, ref_thr) if ref_thr is not None else "—"
        except (ValueError, TypeError):
            thr_f, thr_v = None, "—"
        try:
            lat_f = float(lat)
            lat_v = _verdict(lat_f, ref_lat) if ref_lat is not None else "—"
        except (ValueError, TypeError):
            lat_f, lat_v = None, "—"
        thr_badge = _verdict_badge(thr_v) if thr_v != "—" else "—"
        lat_badge = _verdict_badge(lat_v) if lat_v != "—" else "—"
        html += (
            f"<tr><td>{label}</td>"
            f"<td>{thr or '—'}</td><td>{ref_thr or '—'}</td><td>{thr_badge}</td>"
            f"<td>{lat or '—'}</td><td>{ref_lat or '—'}</td><td>{lat_badge}</td></tr>\n"
        )
    html += "</table>"
    return html


def _fig6_table(ref: dict) -> str:
    stats_file = REPO / "experiments_reproduction" / "experiment3" / "stats.txt"
    rows = _parse_stats_txt(stats_file)
    if not rows:
        return "<p class='muted'>stats.txt not found — run experiment3 first.</p>"

    html = """
    <h3>Experiment parameters</h3>
    <table>
      <tr><th>Parameter</th><th>Value</th></tr>
      <tr><td>Protocols</td><td>Raftel, Chained, Achilles, Hotstuff, Basic-Damysus</td></tr>
      <tr><td>Faults (f)</td><td>8 (n=25)</td></tr>
      <tr><td>Raftel totaltee</td><td>9</td></tr>
      <tr><td>Workload</td><td>100% SET, keyspace=10000</td></tr>
      <tr><td>Value size</td><td>1024 B (1 KB)</td></tr>
      <tr><td>PAYLOAD_SIZE</td><td>1100 B</td></tr>
      <tr><td>Client sweep</td><td>1, 2, 4, 8, 16, 32 clients</td></tr>
      <tr><td>Repeats</td><td>3 per (protocol, clients)</td></tr>
      <tr><td>Network</td><td>WAN — 50 ms one-way netem delay (100 ms RTT)</td></tr>
      <tr><td>SGX mode</td><td>HW</td></tr>
    </table>
    <h3>Paper claim</h3>
    <p class='claim'>§7.6: Peak E2E throughput with Redis KV: Achilles 95 TPS, Chained 92 TPS,
    Raftel 84 TPS, Hotstuff 44 TPS. Achilles ≥ Chained ≥ Raftel &gt; Hotstuff at all
    client counts.</p>
    """

    if not ref:
        html += "<p class='muted warn'>Reference CSV not found — PASS/WARN/FAIL unavailable.</p>"
        return html

    html += """
    <h3>Results vs. reference</h3>
    <table>
      <tr><th>Protocol</th><th>Clients</th>
          <th>Thr measured (kTPS)</th><th>Thr ref</th><th>Thr verdict</th>
          <th>Lat measured (ms)</th><th>Lat ref</th><th>Lat verdict</th></tr>
    """
    for row in rows:
        parts = row.get("_parts")
        if not parts or len(parts) < 4:
            continue
        # CSV: protocol,load_clients,successful_repeats,e2e_throughput_ktps,...
        try:
            protocol = parts[0]
            load_clients = parts[1]
            thr = parts[3]
            lat = parts[4] if len(parts) > 4 else ""
        except IndexError:
            continue
        ref_row = ref.get((protocol, load_clients))
        ref_thr = ref_row["thr"] if ref_row else None
        ref_lat = ref_row["lat"] if ref_row else None
        try:
            thr_f = float(thr)
            thr_v = _verdict(thr_f, ref_thr) if ref_thr is not None else "—"
        except (ValueError, TypeError):
            thr_f, thr_v = None, "—"
        try:
            lat_f = float(lat)
            lat_v = _verdict(lat_f, ref_lat) if ref_lat is not None else "—"
        except (ValueError, TypeError):
            lat_f, lat_v = None, "—"
        thr_badge = _verdict_badge(thr_v) if thr_v != "—" else "—"
        lat_badge = _verdict_badge(lat_v) if lat_v != "—" else "—"
        html += (
            f"<tr><td>{protocol}</td><td>{load_clients}</td>"
            f"<td>{thr or '—'}</td><td>{ref_thr or '—'}</td><td>{thr_badge}</td>"
            f"<td>{lat or '—'}</td><td>{ref_lat or '—'}</td><td>{lat_badge}</td></tr>\n"
        )
    html += "</table>"
    return html


# ---------------------------------------------------------------------------
# Figure metadata
# ---------------------------------------------------------------------------

FIG_META = {
    "fig3": {
        "title": "Figure 3 — WAN Scalability",
        "exp": "experiment1",
        "table_fn": _fig3_table,
    },
    "fig4": {
        "title": "Figure 4 — LAN Leader/Quorum Configurations",
        "exp": "experiment2",
        "table_fn": _fig4_table,
    },
    "fig6": {
        "title": "Figure 6 — Redis KV End-to-End (WAN)",
        "exp": "experiment3",
        "table_fn": _fig6_table,
    },
}


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------

CSS = """
:root {
  --bg: oklch(97% 0 0); --surface: oklch(100% 0 0); --border: oklch(88% 0 0);
  --text: oklch(18% 0 0); --muted: oklch(50% 0 0); --accent: oklch(55% 0.18 240);
  --radius: 6px; --mono: "JetBrains Mono","Fira Mono","Consolas",monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: oklch(13% 0 0); --surface: oklch(17% 0 0); --border: oklch(28% 0 0);
    --text: oklch(92% 0 0); --muted: oklch(60% 0 0); --accent: oklch(72% 0.15 240);
  }
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: system-ui,-apple-system,sans-serif; background: var(--bg);
       color: var(--text); line-height: 1.6; }
header { background: var(--surface); border-bottom: 1px solid var(--border);
         padding: 20px 32px; }
header h1 { font-size: 1.3em; font-weight: 700; }
header .meta { color: var(--muted); font-size: 0.85em; margin-top: 6px; }
main { max-width: 1000px; margin: 0 auto; padding: 32px 24px; }
.summary-card { background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 20px 24px; margin-bottom: 32px;
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px 32px; }
.summary-card dt { font-size: 0.78em; text-transform: uppercase;
  letter-spacing: 0.06em; color: var(--muted); }
.summary-card dd { font-family: var(--mono); font-size: 0.88em;
  margin-top: 2px; word-break: break-all; }
.fig-section { background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 24px; margin-bottom: 24px; }
.fig-section h2 { font-size: 1.1em; font-weight: 600; margin-bottom: 16px; }
.fig-section h3 { font-size: 0.95em; font-weight: 600; margin: 18px 0 8px; }
.claim { color: var(--muted); font-size: 0.88em; margin-bottom: 8px; }
.muted { color: var(--muted); font-size: 0.88em; }
.warn { background: oklch(98% 0.04 60); padding: 8px 12px;
        border-radius: var(--radius); }
table { border-collapse: collapse; width: 100%; font-size: 0.83em;
        margin-top: 4px; }
th, td { border: 1px solid var(--border); padding: 6px 10px; text-align: left; }
th { background: var(--bg); font-weight: 600; }
.verdict { color: #fff; padding: 1px 8px; border-radius: 10px;
           font-size: 0.82em; white-space: nowrap; }
details { margin-top: 24px; }
summary { cursor: pointer; font-weight: 600; font-size: 0.9em;
          color: var(--accent); }
pre { background: var(--bg); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 14px 16px; font-family: var(--mono);
  font-size: 0.8em; overflow-x: auto; margin-top: 10px; white-space: pre-wrap; }
footer { text-align: center; color: var(--muted); font-size: 0.8em;
  padding: 24px; border-top: 1px solid var(--border); margin-top: 40px; }
"""


def build_report(run_dir: Path) -> str:
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    run_id = manifest.get("run_id", run_dir.name)
    git_commit = manifest.get("git_commit", "unknown")
    scale = manifest.get("scale", "unknown")
    status = manifest.get("status", "unknown")
    started = manifest.get("started_at", "")
    finished = manifest.get("finished_at", "")
    figs = manifest.get("figs", list(FIG_META.keys()))
    cluster_ips = manifest.get("cluster_ips", [])
    failed_figs = manifest.get("failed_figs", [])

    checksums = read_file_safe(run_dir / "checksums.txt", "(not available)")
    events_raw = read_file_safe(run_dir / "events.jsonl", "")

    badge_color = {"complete": "#2a7a2a", "running": "#a06000",
                   "failed": "#9a1c1c"}.get(status, "#555")
    status_badge = (
        f'<span style="background:{badge_color};color:#fff;padding:2px 10px;'
        f'border-radius:12px;font-size:0.85em;">{status.upper()}</span>'
    )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Build figure sections
    fig_sections = ""
    for fig in figs:
        meta = FIG_META.get(fig)
        if meta is None:
            continue
        ref = _load_reference_ranges(fig)

        # Image
        img_html = ""
        pdf_path = run_dir / "figures" / f"{fig}.pdf"
        png_path = run_dir / "figures" / f"{fig}.png"
        if pdf_path.exists() and not png_path.exists():
            pdf_to_png(pdf_path, png_path)
        if png_path.exists():
            src = embed_image(png_path)
            img_html = (
                f'<img src="{src}" alt="{meta["title"]}" '
                f'style="max-width:100%;border:1px solid var(--border);'
                f'border-radius:6px;margin-top:12px;">'
            )
        elif pdf_path.exists():
            img_html = (
                f'<p class="muted">PDF: <code>{pdf_path.relative_to(REPO)}</code>'
                f' — install pdftoppm or ImageMagick to embed inline.</p>'
            )
        else:
            img_html = (
                '<p class="muted warn">Figure not yet generated — '
                'run <code>./ae report</code> after the experiment completes.</p>'
            )

        ok = fig not in failed_figs
        icon = "✅" if ok else "❌"
        detail_table = meta["table_fn"](ref)

        fig_sections += f"""
        <section class="fig-section">
          <h2>{icon} {meta['title']}</h2>
          {img_html}
          {detail_table}
        </section>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Raftel AE Report — {run_id}</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>Raftel AE Report {status_badge}</h1>
  <div class="meta">Run ID: <code>{run_id}</code> &nbsp;·&nbsp; Generated: {now}</div>
</header>
<main>
  <dl class="summary-card">
    <div><dt>Git Commit</dt><dd>{git_commit}</dd></div>
    <div><dt>Scale</dt><dd>{scale}</dd></div>
    <div><dt>Started</dt><dd>{started or '—'}</dd></div>
    <div><dt>Finished</dt><dd>{finished or '—'}</dd></div>
    <div><dt>Cluster Hosts</dt>
      <dd>{len(cluster_ips)} IP(s): {', '.join(cluster_ips[:4])}{' …' if len(cluster_ips) > 4 else ''}</dd>
    </div>
    <div><dt>Failed Experiments</dt>
      <dd>{'None' if not failed_figs else ', '.join(failed_figs)}</dd>
    </div>
  </dl>

  {fig_sections}

  <details>
    <summary>Script Checksums (anti-tampering audit trail)</summary>
    <pre>{checksums}</pre>
  </details>
  <details>
    <summary>Event Log (events.jsonl)</summary>
    <pre>{events_raw or '(empty)'}</pre>
  </details>
</main>
<footer>Raftel Artifact Evaluation &nbsp;·&nbsp; Run {run_id}</footer>
</body>
</html>
"""
    return html


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <run_dir>", file=sys.stderr)
        sys.exit(1)
    run_dir = Path(sys.argv[1])
    if not run_dir.exists():
        print(f"Run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    # Run plot scripts to generate figures first
    import os
    for fig, meta in FIG_META.items():
        plot_script = REPO / "scripts" / f"plot_{fig}.py"
        if plot_script.exists():
            stats_file = (
                REPO / "experiments_reproduction" / meta["exp"] / "stats.txt"
            )
            if stats_file.exists():
                env = os.environ.copy()
                env["AE_RUN_DIR"] = str(run_dir)
                subprocess.call([sys.executable, str(plot_script)], env=env)

    html = build_report(run_dir)
    out = run_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"Report written: {out}")


if __name__ == "__main__":
    main()
