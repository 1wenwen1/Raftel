#!/usr/bin/env python3
"""Generate a standalone HTML report from a run directory.

Usage: python3 gen_report.py <run_dir>

Reads:
  <run_dir>/manifest.json
  <run_dir>/figures/fig{3,4,6}.pdf  (converted to PNG for embedding)
  experiments_reproduction/experiment{1,2,3}/stats.txt
  <run_dir>/checksums.txt

Writes:
  <run_dir>/index.html  (self-contained, no external deps)
"""

import base64
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def pdf_to_png(pdf_path: Path, out_png: Path) -> bool:
    """Convert PDF to PNG via pdftoppm or convert (ImageMagick)."""
    if shutil.which("pdftoppm"):
        rc = subprocess.call(
            ["pdftoppm", "-r", "150", "-l", "1", "-png", str(pdf_path), str(out_png.with_suffix(""))],
        )
        candidate = out_png.with_suffix("").parent / (out_png.stem + "-1.png")
        if candidate.exists():
            candidate.rename(out_png)
            return True
    if shutil.which("convert"):
        rc = subprocess.call(["convert", "-density", "150", f"{pdf_path}[0]", str(out_png)])
        return rc == 0
    return False


def embed_image(path: Path) -> str:
    """Return a base64 data-URL for an image file."""
    suffix = path.suffix.lower()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "svg": "image/svg+xml"}.get(suffix[1:], "image/png")
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{data}"


def read_file_safe(path: Path, default="") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return default


FIG_META = {
    "fig3": {"title": "Figure 3 — WAN Scalability", "exp": "experiment1", "claim": "Throughput and latency vs. number of faults across protocols"},
    "fig4": {"title": "Figure 4 — LAN Leader/Quorum Configurations", "exp": "experiment2", "claim": "Raftel variants (S1–S4): TEE/non-TEE leader × TEE population"},
    "fig6": {"title": "Figure 6 — Redis KV End-to-End (WAN)", "exp": "experiment3", "claim": "Throughput-latency curves across protocols, f=8, 50ms WAN delay"},
}


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

    # Build figure sections
    fig_sections = ""
    for fig in figs:
        meta = FIG_META.get(fig, {"title": fig, "exp": "", "claim": ""})
        img_html = ""

        # Try PDF->PNG conversion
        pdf_path = run_dir / "figures" / f"{fig}.pdf"
        png_path = run_dir / "figures" / f"{fig}.png"
        if pdf_path.exists() and not png_path.exists():
            pdf_to_png(pdf_path, png_path)
        if png_path.exists():
            src = embed_image(png_path)
            img_html = f'<img src="{src}" alt="{meta["title"]}" style="max-width:100%;border:1px solid var(--border);border-radius:6px;">'
        elif pdf_path.exists():
            img_html = f'<p class="muted">PDF available: <code>{pdf_path.relative_to(REPO)}</code> — install pdftoppm or ImageMagick to embed.</p>'
        else:
            img_html = '<p class="muted warn">Figure not yet generated — run <code>./ae report</code> after the experiment completes.</p>'

        result_indicator = "✅" if fig not in failed_figs else "❌"
        fig_sections += f"""
        <section class="fig-section">
          <h2>{result_indicator} {meta['title']}</h2>
          <p class="claim">{meta['claim']}</p>
          {img_html}
        </section>
        """

    # Status badge
    badge_color = {"complete": "#2a7a2a", "running": "#a06000", "failed": "#9a1c1c"}.get(status, "#555")
    status_badge = f'<span style="background:{badge_color};color:#fff;padding:2px 10px;border-radius:12px;font-size:0.85em;">{status.upper()}</span>'

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Raftel AE Report — {run_id}</title>
<style>
  :root {{
    --bg: oklch(97% 0 0);
    --surface: oklch(100% 0 0);
    --border: oklch(88% 0 0);
    --text: oklch(18% 0 0);
    --muted: oklch(50% 0 0);
    --accent: oklch(55% 0.18 240);
    --accent-bg: oklch(96% 0.04 240);
    --warn-bg: oklch(98% 0.04 60);
    --radius: 6px;
    --mono: "JetBrains Mono","Fira Mono","Consolas",monospace;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: oklch(13% 0 0);
      --surface: oklch(17% 0 0);
      --border: oklch(28% 0 0);
      --text: oklch(92% 0 0);
      --muted: oklch(60% 0 0);
      --accent: oklch(72% 0.15 240);
      --accent-bg: oklch(20% 0.05 240);
      --warn-bg: oklch(18% 0.05 60);
    }}
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: system-ui,-apple-system,sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }}
  header {{ background: var(--surface); border-bottom: 1px solid var(--border); padding: 20px 32px; }}
  header h1 {{ font-size: 1.3em; font-weight: 700; letter-spacing: -0.02em; }}
  header .meta {{ color: var(--muted); font-size: 0.85em; margin-top: 6px; }}
  main {{ max-width: 960px; margin: 0 auto; padding: 32px 24px; }}
  .summary-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px 24px; margin-bottom: 32px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px 32px; }}
  .summary-card dt {{ font-size: 0.78em; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }}
  .summary-card dd {{ font-size: 0.92em; font-family: var(--mono); margin-top: 2px; word-break: break-all; }}
  .fig-section {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 24px; margin-bottom: 24px; }}
  .fig-section h2 {{ font-size: 1.05em; font-weight: 600; margin-bottom: 6px; }}
  .claim {{ color: var(--muted); font-size: 0.88em; margin-bottom: 16px; }}
  .muted {{ color: var(--muted); font-size: 0.88em; }}
  .warn {{ background: var(--warn-bg); padding: 10px 14px; border-radius: var(--radius); }}
  details {{ margin-top: 24px; }}
  summary {{ cursor: pointer; font-weight: 600; font-size: 0.9em; color: var(--accent); }}
  pre {{ background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; font-family: var(--mono); font-size: 0.8em; overflow-x: auto; margin-top: 10px; white-space: pre-wrap; word-break: break-word; }}
  footer {{ text-align: center; color: var(--muted); font-size: 0.8em; padding: 24px; border-top: 1px solid var(--border); margin-top: 40px; }}
</style>
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
    <div><dt>Cluster Hosts</dt><dd>{len(cluster_ips)} IP(s): {', '.join(cluster_ips[:4])}{' …' if len(cluster_ips)>4 else ''}</dd></div>
    <div><dt>Failed Experiments</dt><dd>{'None' if not failed_figs else ', '.join(failed_figs)}</dd></div>
  </dl>

  {fig_sections}

  <details>
    <summary>Script Checksums (anti-tampering audit trail)</summary>
    <pre>{checksums}</pre>
  </details>
</main>
<footer>Raftel Artifact Evaluation &nbsp;·&nbsp; Run {run_id}</footer>
</body>
</html>
"""
    return html


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <run_dir>", file=sys.stderr)
        sys.exit(1)
    run_dir = Path(sys.argv[1])
    if not run_dir.exists():
        print(f"Run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    # Run plot scripts to generate figures first
    for fig, meta in FIG_META.items():
        plot_script = REPO / "scripts" / f"plot_{fig}.py"
        if plot_script.exists():
            stats_file = REPO / "experiments_reproduction" / meta["exp"] / "stats.txt"
            if stats_file.exists():
                import os
                env = os.environ.copy()
                env["AE_RUN_DIR"] = str(run_dir)
                subprocess.call([sys.executable, str(plot_script)], env=env)

    html = build_report(run_dir)
    out = run_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"Report written: {out}")


if __name__ == "__main__":
    main()
