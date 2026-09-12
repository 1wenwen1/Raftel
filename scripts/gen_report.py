#!/usr/bin/env python3
from __future__ import annotations

"""Generate a standalone HTML report from a run directory.

Usage: python3 gen_report.py <run_dir>

Reads:
  <run_dir>/manifest.json
  <run_dir>/figures/fig{3,4,6}.pdf  (converted to PNG for embedding)
  experiments_reproduction/experiment{1,2,3}/stats.txt
  runs/reference/fig{3,4,6}.csv
  <run_dir>/checksums.txt
  <run_dir>/events.jsonl

Writes:
  <run_dir>/index.html  (self-contained, no external deps)
"""

import base64
import csv
import io
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REFERENCE_DIR = REPO / "runs" / "reference"
GITHUB_REPO = "https://github.com/1wenwen1/Raftel"

# ---------------------------------------------------------------------------
# Ordering expectations for ranking verification
# ---------------------------------------------------------------------------
# For each figure we define the expected ranking as a list of lists;
# protocols within the same inner list are considered equivalent.
EXPECTED_THR_ORDER = {
    "fig3": [["Achilles"], ["Chained"], ["Raftel"], ["Hotstuff", "Basic-Damysus", "Raftel-Worst"]],
    "fig4": [["set1"], ["set2", "set3"], ["set4"]],
    "fig6": [["Achilles"], ["Chained"], ["Raftel"], ["Basic-Damysus"], ["Hotstuff"]],
}
EXPECTED_LAT_ORDER = {
    "fig3": [["Raftel", "Chained"], ["Basic-Damysus"], ["Hotstuff", "Raftel-Worst"]],
    "fig4": [["set1"], ["set2"], ["set3"], ["set4"]],
}


# ---------------------------------------------------------------------------
# PDF → PNG
# ---------------------------------------------------------------------------
def pdf_to_png(pdf_path: Path, out_png: Path) -> bool:
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
    suffix = path.suffix.lower()
    mime = {"png": "image/png", "jpg": "image/jpeg",
            "jpeg": "image/jpeg", "svg": "image/svg+xml"}.get(suffix[1:], "image/png")
    data = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{data}"


def read_file_safe(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------
def _load_reference(fig: str) -> dict:
    csv_path = REFERENCE_DIR / f"{fig}.csv"
    if not csv_path.exists():
        return {}
    raw = [l for l in csv_path.read_text(encoding="utf-8").splitlines()
           if l.strip() and not l.strip().startswith("#")]
    result = {}
    with io.StringIO("\n".join(raw)) as f:
        for row in csv.DictReader(f):
            try:
                if fig == "fig3":
                    key = (row["protocol"], row["faults"])
                    result[key] = {"thr": float(row["throughput_ktps"]),
                                   "lat": float(row["latency_ms"])}
                elif fig == "fig4":
                    key = (row["set"], row["faults"])
                    result[key] = {"thr": float(row["throughput_ktps"]),
                                   "lat": float(row["latency_ms"])}
                elif fig == "fig6":
                    key = (row["protocol"], row["load_clients"])
                    result[key] = {"thr": float(row["throughput_ktps"]),
                                   "lat": float(row["latency_avg_ms"])}
            except (KeyError, ValueError):
                continue
    return result


# ---------------------------------------------------------------------------
# Stats parsing
# ---------------------------------------------------------------------------
def _parse_stats(stats_file: Path) -> list[dict]:
    rows = []
    if not stats_file.exists():
        return rows
    for line in stats_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        row: dict = {"_raw": line, "_parts": parts}
        if "=" in line:
            row["label"] = parts[0] if parts else ""
            for token in parts[1:]:
                if "=" in token:
                    k, v = token.split("=", 1)
                    row[k.strip()] = v.strip()
        elif len(parts) >= 3:
            # Figure 3/4 sweep scripts write: label, throughput, latency.
            row["label"] = parts[0]
            row["thr_view"] = parts[1]
            row["lat_view"] = parts[2]
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Ranking verification
# ---------------------------------------------------------------------------
def _check_ordering(measured_avgs: dict, expected_order: list[list[str]]) -> tuple[bool, str]:
    """Return (ok, description).  measured_avgs: {name -> float}, higher is better."""
    groups = [g for g in expected_order if any(k in measured_avgs for k in g)]
    if len(groups) < 2:
        return True, "insufficient data to verify ordering"
    violations = []
    for i in range(len(groups) - 1):
        hi_group = groups[i]
        lo_group = groups[i + 1]
        hi_vals = [measured_avgs[k] for k in hi_group if k in measured_avgs]
        lo_vals = [measured_avgs[k] for k in lo_group if k in measured_avgs]
        if not hi_vals or not lo_vals:
            continue
        hi_avg = sum(hi_vals) / len(hi_vals)
        lo_avg = sum(lo_vals) / len(lo_vals)
        if hi_avg < lo_avg * 0.9:   # 10% tolerance
            violations.append(
                f"{'+'.join(hi_group)} ({hi_avg:.2f}) < {'+'.join(lo_group)} ({lo_avg:.2f})"
            )
    ok = len(violations) == 0
    desc = "ordering matches paper" if ok else f"ordering violation: {'; '.join(violations)}"
    return ok, desc


# ---------------------------------------------------------------------------
# Per-figure data summary (for claim cards and summary section)
# ---------------------------------------------------------------------------
def _fig3_summary(ref: dict, stats_file: Path) -> dict:
    rows = _parse_stats(stats_file)
    if not rows:
        return {"status": "no_data"}

    # Collect average throughput per protocol across all fault values
    proto_thr: dict = {}
    for row in rows:
        label = row.get("label", "")
        thr = row.get("thr_view", "")
        m = re.match(r"^(.+?)_f(\d+)$", label)
        if not m or not thr:
            continue
        proto = m.group(1)
        try:
            proto_thr.setdefault(proto, []).append(float(thr))
        except ValueError:
            pass
    avg_thr = {p: sum(vs) / len(vs) for p, vs in proto_thr.items()}

    ok, desc = _check_ordering(avg_thr, EXPECTED_THR_ORDER["fig3"])
    return {"status": "ok", "ordering_ok": ok, "ordering_desc": desc,
            "avg_thr": avg_thr, "rows": rows, "ref": ref}


def _fig4_summary(ref: dict, stats_file: Path) -> dict:
    rows = _parse_stats(stats_file)
    if not rows:
        return {"status": "no_data"}

    set_thr: dict = {}
    for row in rows:
        label = row.get("label", "")
        thr = row.get("thr_view", "")
        m = re.match(r"^(set\d)_f(\d+)$", label)
        if not m or not thr:
            continue
        set_name = m.group(1)
        try:
            set_thr.setdefault(set_name, []).append(float(thr))
        except ValueError:
            pass
    avg_thr = {s: sum(vs) / len(vs) for s, vs in set_thr.items()}

    # Check paper-exact value: S1 at f=32 = 31.5 kTPS
    s1_f32_row = next(
        (r for r in rows if r.get("label", "") == "set1_f32"), None
    )
    s1_f32_measured = float(s1_f32_row.get("thr_view", 0)) if s1_f32_row else None

    ok, desc = _check_ordering(avg_thr, EXPECTED_THR_ORDER["fig4"])
    return {"status": "ok", "ordering_ok": ok, "ordering_desc": desc,
            "avg_thr": avg_thr, "s1_f32": s1_f32_measured, "rows": rows, "ref": ref}


def _fig6_summary(ref: dict, stats_file: Path) -> dict:
    rows = _parse_stats(stats_file)
    if not rows:
        return {"status": "no_data"}

    # Find peak throughput per protocol
    proto_peak: dict = {}
    for row in rows:
        parts = row.get("_parts", [])
        if len(parts) < 4:
            continue
        protocol = parts[0]
        if protocol == "protocol":
            continue
        try:
            thr_tps = float(parts[3]) * 1000.0  # kTPS → TPS
        except (ValueError, IndexError):
            continue
        if protocol not in proto_peak or thr_tps > proto_peak[protocol]:
            proto_peak[protocol] = thr_tps

    # Convert to kTPS for ordering check
    proto_peak_k = {p: v / 1000.0 for p, v in proto_peak.items()}
    ok, desc = _check_ordering(proto_peak_k, EXPECTED_THR_ORDER["fig6"])

    # Paper-exact peaks (TPS): Achilles=95, Chained=92, Raftel=84, Hotstuff=44
    paper_peaks = {"Raftel": 84, "Chained": 92, "Achilles": 95, "Hotstuff": 44}
    return {"status": "ok", "ordering_ok": ok, "ordering_desc": desc,
            "proto_peak": proto_peak, "paper_peaks": paper_peaks, "rows": rows, "ref": ref}


# ---------------------------------------------------------------------------
# Events timeline
# ---------------------------------------------------------------------------
def _parse_events(run_dir: Path) -> list[dict]:
    events_file = run_dir / "events.jsonl"
    events = []
    for line in read_file_safe(events_file).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return events


def _format_events_html(events: list[dict]) -> str:
    if not events:
        return "<p class='muted'>No events recorded.</p>"
    rows = ""
    for ev in events:
        ts = ev.get("timestamp", "")
        # Shorten ISO timestamp to HH:MM:SS
        ts_short = ts[11:19] if len(ts) >= 19 else ts
        event_type = ev.get("event", "")
        detail = ""
        if event_type == "run_start":
            detail = f"Experiment started — figs: {', '.join(ev.get('figs', []))}, scale: {ev.get('scale', '')}"
        elif event_type == "fig_start":
            detail = f"▶ {ev.get('fig', '')} started"
        elif event_type == "fig_end":
            rc = ev.get("exit", "?")
            status = "✓ complete" if rc == 0 else f"✗ failed (exit {rc})"
            detail = f"■ {ev.get('fig', '')} {status}"
        elif event_type == "run_end":
            failed = ev.get("failed_figs", [])
            detail = f"Run finished — {'all passed' if not failed else 'failed: ' + ', '.join(failed)}"
        else:
            detail = json.dumps({k: v for k, v in ev.items() if k not in ("timestamp", "event")})
        rows += f"<tr><td class='ts'>{ts_short}</td><td>{detail}</td></tr>\n"
    return f"<table class='event-table'><tbody>{rows}</tbody></table>"


def _compute_duration(events: list[dict]) -> str:
    start = next((e.get("timestamp") for e in events if e.get("event") == "run_start"), None)
    end = next((e.get("timestamp") for e in reversed(events) if e.get("event") == "run_end"), None)
    if not start or not end:
        return ""
    try:
        t0 = datetime.fromisoformat(start.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(end.replace("Z", "+00:00"))
        secs = int((t1 - t0).total_seconds())
        h, r = divmod(secs, 3600)
        m, s = divmod(r, 60)
        return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# HTML components
# ---------------------------------------------------------------------------
def _icon(ok: bool | None) -> str:
    if ok is None:
        return '<span class="icon-muted">—</span>'
    return '<span class="icon-ok">✓</span>' if ok else '<span class="icon-warn">⚠</span>'


def _claim_card(fig_id: str, title: str, summary: dict) -> str:
    if summary.get("status") == "no_data":
        ordering_line = "<span class='muted'>No data yet — run the experiment first.</span>"
    else:
        ok = summary.get("ordering_ok")
        desc = summary.get("ordering_desc", "")
        ordering_line = f"{_icon(ok)} {desc}"

    # Extra fact for fig4
    extra = ""
    if fig_id == "fig4" and summary.get("s1_f32") is not None:
        paper_val = 31.5
        measured = summary["s1_f32"]
        delta_pct = abs(measured - paper_val) / paper_val * 100
        extra = (f"<div class='card-extra'>S1 at f=32: measured {measured:.1f} kTPS "
                 f"(paper 31.5 kTPS, {delta_pct:.0f}% deviation)</div>")

    # Extra for fig6: peak comparison
    if fig_id == "fig6" and summary.get("proto_peak"):
        lines = []
        for proto, paper_tps in sorted(summary.get("paper_peaks", {}).items()):
            meas = summary["proto_peak"].get(proto)
            if meas is not None:
                delta = abs(meas - paper_tps) / paper_tps * 100
                lines.append(f"{proto}: {meas:.0f} TPS (paper {paper_tps} TPS, Δ{delta:.0f}%)")
        if lines:
            extra = "<div class='card-extra'>" + " &nbsp;·&nbsp; ".join(lines) + "</div>"

    return f"""<div class="claim-card">
  <div class="card-label">{title}</div>
  <div class="card-ordering">{ordering_line}</div>
  {extra}
</div>"""


def _fig_image_html(run_dir: Path, fig_id: str) -> str:
    pdf_path = run_dir / "figures" / f"{fig_id}.pdf"
    png_path = run_dir / "figures" / f"{fig_id}.png"
    if pdf_path.exists() and not png_path.exists():
        pdf_to_png(pdf_path, png_path)
    if png_path.exists():
        src = embed_image(png_path)
        return f'<img src="{src}" alt="{fig_id}" class="fig-img">'
    if pdf_path.exists():
        return (f'<p class="muted">PDF available — install <code>poppler-utils</code> '
                f'or ImageMagick to embed inline.</p>')
    return '<p class="muted">Figure not yet generated. Run <code>./ae report</code> after the experiment.</p>'


def _detail_table_fig3(summary: dict) -> str:
    rows = summary.get("rows", [])
    ref = summary.get("ref", {})
    if not rows:
        return ""
    html = ("<table><tr><th>Config</th>"
            "<th>Thr (kTPS)</th><th>Ref thr</th>"
            "<th>Lat (ms)</th><th>Ref lat</th></tr>\n")
    for row in rows:
        label = row.get("label", "")
        thr = row.get("thr_view", "—")
        lat = row.get("lat_view", "—")
        m = re.match(r"^(.+?)_f(\d+)$", label)
        ref_thr = ref_lat = "—"
        if m:
            r = ref.get((m.group(1), m.group(2)))
            if r:
                ref_thr = f"{r['thr']:.1f}"
                ref_lat = f"{r['lat']:.0f}"
        html += f"<tr><td>{label}</td><td>{thr}</td><td>{ref_thr}</td><td>{lat}</td><td>{ref_lat}</td></tr>\n"
    html += "</table>"
    return html


def _detail_table_fig4(summary: dict) -> str:
    rows = summary.get("rows", [])
    ref = summary.get("ref", {})
    if not rows:
        return ""
    html = ("<table><tr><th>Config</th>"
            "<th>Thr (kTPS)</th><th>Ref thr</th>"
            "<th>Lat (ms)</th><th>Ref lat</th></tr>\n")
    for row in rows:
        label = row.get("label", "")
        thr = row.get("thr_view", "—")
        lat = row.get("lat_view", "—")
        m = re.match(r"^(set\d)_f(\d+)$", label)
        ref_thr = ref_lat = "—"
        if m:
            r = ref.get((m.group(1), m.group(2)))
            if r:
                ref_thr = f"{r['thr']:.1f}"
                ref_lat = f"{r['lat']:.0f}"
        html += f"<tr><td>{label}</td><td>{thr}</td><td>{ref_thr}</td><td>{lat}</td><td>{ref_lat}</td></tr>\n"
    html += "</table>"
    return html


def _detail_table_fig6(summary: dict) -> str:
    rows = summary.get("rows", [])
    ref = summary.get("ref", {})
    if not rows:
        return ""
    html = ("<table><tr><th>Protocol</th><th>Clients</th>"
            "<th>Thr (TPS)</th><th>Ref thr (TPS)</th>"
            "<th>Lat avg (ms)</th></tr>\n")
    for row in rows:
        parts = row.get("_parts", [])
        if len(parts) < 5 or parts[0] == "protocol":
            continue
        try:
            protocol = parts[0]
            clients = parts[1]
            thr_tps = f"{float(parts[3]) * 1000:.1f}"
            lat = f"{float(parts[4]):.0f}"
            r = ref.get((protocol, clients))
            ref_thr = f"{r['thr'] * 1000:.1f}" if r else "—"
        except (ValueError, IndexError):
            continue
        html += f"<tr><td>{protocol}</td><td>{clients}</td><td>{thr_tps}</td><td>{ref_thr}</td><td>{lat}</td></tr>\n"
    html += "</table>"
    return html


def _config_table(fig_id: str) -> str:
    configs = {
        "fig3": [
            ("Protocols", "Raftel, Chained, Achilles, Hotstuff, Basic-Damysus, Raftel-Worst"),
            ("Fault values (f)", "1, 2, 4, 8, 16, 32"),
            ("Batch size", "400 tx/block"),
            ("Payload", "256 B"),
            ("Network", "WAN — 50 ms one-way netem (100 ms RTT)"),
            ("SGX mode", "HW"),
            ("Raftel totaltee", "f+1 (Raftel-Best); 0 for Raftel-Worst (§7.2)"),
            ("Warm-up", "5 views per config point, result discarded"),
        ],
        "fig4": [
            ("Sets", "S1: TEE leader totaltee=f+1 · S2: TEE leader totaltee=f · S3: non-TEE leader totaltee=f+1 · S4: non-TEE leader totaltee=f"),
            ("Fault values (f)", "1, 2, 4, 8, 16, 32"),
            ("Batch size", "400 tx/block"),
            ("Payload", "256 B"),
            ("Network", "LAN — no WAN delay"),
            ("SGX mode", "HW"),
            ("Warm-up", "5 views per config point, result discarded"),
        ],
        "fig6": [
            ("Protocols", "Raftel, Chained, Achilles, Hotstuff, Basic-Damysus"),
            ("Faults (f)", "8 (n=25)"),
            ("Raftel totaltee", "9"),
            ("Workload", "100% SET, keyspace=10000"),
            ("Value size", "1024 B (1 KB) — §7.6"),
            ("PAYLOAD_SIZE", "1100 B (key + 1024 + 14-byte header ≤ 1100)"),
            ("Client sweep", "1, 2, 4, 8, 16, 32 clients"),
            ("Repeats", "3 per (protocol, clients)"),
            ("Network", "WAN — 50 ms one-way netem (100 ms RTT)"),
            ("SGX mode", "HW"),
            ("Warm-up", "5 views per (protocol, clients) point, result discarded"),
        ],
    }
    rows = "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in configs.get(fig_id, []))
    return f"<table><tr><th>Parameter</th><th>Value</th></tr>{rows}</table>"


def _claims_text(fig_id: str) -> str:
    claims = {
        "fig3": ("§7.2 — Raftel achieves throughput comparable to Chained and significantly "
                 "better than Hotstuff and Raftel-Worst, while its latency is lower than or "
                 "equal to Chained. Achilles leads in throughput due to its smaller 2f+1 quorum."),
        "fig4": ("§7.3 — TEE leadership and a full TEE quorum (S1) yield the highest throughput "
                 "and lowest latency. Removing either degrades performance: S1 > S2 ≥ S3 > S4 "
                 "for throughput; S1 ≤ S2 ≤ S3 ≤ S4 for latency. S1 at f=32 achieves 31.5 kTPS."),
        "fig6": ("§7.6 — Redis KV end-to-end peak throughput (WAN, f=8): Achilles 95 TPS, "
                 "Chained 92 TPS, Raftel 84 TPS, Hotstuff 44 TPS. Protocol ordering consistent "
                 "with Figs 3 and 4 across all client counts."),
    }
    return claims.get(fig_id, "")


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------
def build_report(run_dir: Path) -> str:
    manifest = {}
    mp = run_dir / "manifest.json"
    if mp.exists():
        try:
            manifest = json.loads(mp.read_text())
        except Exception:
            pass

    run_id = manifest.get("run_id", run_dir.name)
    git_commit = manifest.get("git_commit", "unknown")
    git_commit_short = git_commit[:12] if len(git_commit) > 12 else git_commit
    git_url = f"{GITHUB_REPO}/commit/{git_commit}" if "unknown" not in git_commit else "#"
    scale = manifest.get("scale", "unknown")
    status = manifest.get("status", "unknown")
    started = manifest.get("started_at", "")
    finished = manifest.get("finished_at", "")
    figs = manifest.get("figs", ["fig3", "fig4", "fig6"])
    cluster_ips = manifest.get("cluster_ips", [])
    failed_figs = manifest.get("failed_figs", [])

    checksums_raw = read_file_safe(run_dir / "checksums.txt", "")
    events = _parse_events(run_dir)
    duration = _compute_duration(events)
    events_html = _format_events_html(events)

    # Checksums with verification hint
    checksums_html = ""
    if checksums_raw:
        lines = []
        for line in checksums_raw.strip().splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                digest, path = parts
                lines.append(
                    f'<tr><td class="mono">{digest[:16]}…</td>'
                    f'<td class="mono">{path}</td>'
                    f'<td class="verify-hint">git show {git_commit_short}:{path} | sha256sum</td></tr>'
                )
        checksums_html = (
            "<p class='muted-sm'>Verify each file against the committed version by running "
            "the command in the rightmost column on any machine with the repository.</p>"
            "<table class='chk-table'><tr><th>SHA-256 (first 16)</th>"
            "<th>Path</th><th>Verify command</th></tr>"
            + "".join(lines) + "</table>"
        )
    else:
        checksums_html = "<p class='muted'>No checksums file found.</p>"

    # Load summaries
    summaries = {
        "fig3": _fig3_summary(_load_reference("fig3"), run_dir / "stats" / "fig3.txt"),
        "fig4": _fig4_summary(_load_reference("fig4"), run_dir / "stats" / "fig4.txt"),
        "fig6": _fig6_summary(_load_reference("fig6"), run_dir / "stats" / "fig6.txt"),
    }

    FIG_TITLES = {
        "fig3": "Figure 3 — WAN Scalability",
        "fig4": "Figure 4 — LAN Leader / Quorum Configurations",
        "fig6": "Figure 6 — Redis KV End-to-End (WAN)",
    }
    DETAIL_FNS = {
        "fig3": _detail_table_fig3,
        "fig4": _detail_table_fig4,
        "fig6": _detail_table_fig6,
    }

    # Claim cards (top summary)
    claim_cards_html = "\n".join(
        _claim_card(fig, FIG_TITLES.get(fig, fig), summaries.get(fig, {"status": "no_data"}))
        for fig in ["fig3", "fig4", "fig6"]
    )

    # Figure sections
    fig_sections_html = ""
    for fig in figs:
        title = FIG_TITLES.get(fig, fig)
        failed = fig in failed_figs
        status_icon = "❌" if failed else "✅"
        img = _fig_image_html(run_dir, fig)
        claim_text = _claims_text(fig)
        summary = summaries.get(fig, {"status": "no_data"})
        ordering_ok = summary.get("ordering_ok")
        ordering_desc = summary.get("ordering_desc", "")
        ordering_html = (
            f'<div class="ordering-line">{_icon(ordering_ok)} {ordering_desc}</div>'
            if ordering_desc else ""
        )
        detail_table = DETAIL_FNS.get(fig, lambda _: "")(summary)
        config_table = _config_table(fig)

        fig_sections_html += f"""
<section class="fig-section">
  <h2>{status_icon} {title}</h2>
  <div class="fig-body">
    <div class="fig-img-wrap">{img}</div>
    <div class="fig-meta">
      <p class="claim-text">{claim_text}</p>
      {ordering_html}
    </div>
  </div>
  <details class="detail-block">
    <summary>Numerical results vs. reference</summary>
    {detail_table if detail_table else "<p class='muted'>No data yet.</p>"}
  </details>
  <details class="detail-block">
    <summary>Experiment configuration</summary>
    {config_table}
  </details>
</section>
"""

    # Status color
    status_color = {"complete": "var(--green)", "running": "var(--warn)",
                    "failed": "var(--red)"}.get(status, "var(--muted)")

    started_fmt = started[:19].replace("T", " ") if started else "—"
    finished_fmt = finished[:19].replace("T", " ") if finished else "—"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    ip_list_html = (", ".join(cluster_ips[:6]) + (" …" if len(cluster_ips) > 6 else "")
                    ) if cluster_ips else "—"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Raftel AE — {run_id}</title>
<style>
/* --- tokens --- */
:root {{
  --bg:      oklch(97% 0 0);
  --surface: oklch(100% 0 0);
  --border:  oklch(88% 0 0);
  --text:    oklch(16% 0 0);
  --muted:   oklch(48% 0 0);
  --accent:  oklch(48% 0.14 240);
  --green:   oklch(42% 0.15 145);
  --warn:    oklch(52% 0.15 65);
  --red:     oklch(48% 0.18 25);
  --radius:  6px;
  --mono: "JetBrains Mono","Fira Mono","Consolas",monospace;
  --serif: "Georgia","Times New Roman",serif;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg:      oklch(13% 0 0);
    --surface: oklch(18% 0 0);
    --border:  oklch(28% 0 0);
    --text:    oklch(92% 0 0);
    --muted:   oklch(60% 0 0);
    --accent:  oklch(68% 0.12 240);
    --green:   oklch(62% 0.14 145);
    --warn:    oklch(68% 0.13 65);
    --red:     oklch(65% 0.16 25);
  }}
}}
*,*::before,*::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: system-ui,-apple-system,sans-serif; background: var(--bg);
       color: var(--text); line-height: 1.6; font-size: 15px; }}

/* --- layout --- */
header {{ background: var(--surface); border-bottom: 1px solid var(--border);
         padding: 18px 32px; display: flex; align-items: baseline;
         gap: 16px; flex-wrap: wrap; }}
header h1 {{ font-size: 1.15em; font-weight: 700; letter-spacing: -0.01em; }}
header .run-meta {{ font-size: 0.82em; color: var(--muted); font-family: var(--mono); }}
header .status-dot {{ display: inline-block; width: 8px; height: 8px;
  border-radius: 50%; background: {status_color}; margin-right: 6px; vertical-align: middle; }}
main {{ max-width: 1040px; margin: 0 auto; padding: 28px 24px; }}

/* --- claim cards --- */
.claim-cards {{ display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 16px; margin-bottom: 36px; }}
@media (max-width: 720px) {{ .claim-cards {{ grid-template-columns: 1fr; }} }}
.claim-card {{ background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 16px 18px; }}
.card-label {{ font-size: 0.78em; text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--muted); margin-bottom: 6px; }}
.card-ordering {{ font-size: 0.9em; line-height: 1.4; }}
.card-extra {{ font-size: 0.8em; color: var(--muted); margin-top: 8px;
  font-family: var(--mono); }}

/* --- figure sections --- */
.fig-section {{ background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 24px; margin-bottom: 24px; }}
.fig-section h2 {{ font-size: 1.05em; font-weight: 600; margin-bottom: 16px; }}
.fig-body {{ display: grid; grid-template-columns: 1fr 340px; gap: 24px;
  align-items: start; }}
@media (max-width: 800px) {{ .fig-body {{ grid-template-columns: 1fr; }} }}
.fig-img-wrap img.fig-img {{ width: 100%; border: 1px solid var(--border);
  border-radius: var(--radius); }}
.fig-meta {{ display: flex; flex-direction: column; gap: 12px; }}
.claim-text {{ font-size: 0.87em; color: var(--muted); font-family: var(--serif);
  line-height: 1.55; font-style: italic; }}
.ordering-line {{ font-size: 0.88em; }}

/* --- detail blocks --- */
.detail-block {{ margin-top: 16px; border-top: 1px solid var(--border); padding-top: 12px; }}
.detail-block > summary {{ cursor: pointer; font-size: 0.85em; font-weight: 600;
  color: var(--accent); user-select: none; }}
.detail-block > summary:hover {{ opacity: 0.8; }}

/* --- tables --- */
table {{ border-collapse: collapse; width: 100%; font-size: 0.81em; margin-top: 10px; }}
th, td {{ border: 1px solid var(--border); padding: 5px 10px; text-align: left; }}
th {{ background: var(--bg); font-weight: 600; }}
.chk-table td.verify-hint {{ font-size: 0.75em; color: var(--muted);
  font-family: var(--mono); }}
.event-table {{ border: none; width: 100%; }}
.event-table td {{ border: none; padding: 2px 8px; font-size: 0.83em; }}
.event-table td.ts {{ font-family: var(--mono); color: var(--muted);
  white-space: nowrap; width: 70px; }}

/* --- audit section --- */
.audit-section {{ background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 20px 24px; margin-bottom: 24px; }}
.audit-section h2 {{ font-size: 0.95em; font-weight: 600; margin-bottom: 14px;
  color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }}
.audit-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }}
@media (max-width: 640px) {{ .audit-grid {{ grid-template-columns: 1fr; }} }}
.audit-block h3 {{ font-size: 0.82em; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.05em; color: var(--muted); margin-bottom: 8px; }}
.audit-row {{ font-size: 0.85em; margin-bottom: 4px; }}
.audit-row .key {{ color: var(--muted); display: inline-block; min-width: 100px; }}
.audit-row a {{ color: var(--accent); text-decoration: none; }}
.audit-row a:hover {{ text-decoration: underline; }}

/* --- icons --- */
.icon-ok  {{ color: var(--green); font-style: normal; }}
.icon-warn {{ color: var(--warn); font-style: normal; }}
.icon-muted {{ color: var(--muted); }}

/* --- misc --- */
.muted {{ color: var(--muted); font-size: 0.87em; }}
.muted-sm {{ color: var(--muted); font-size: 0.8em; margin-bottom: 8px; }}
.mono {{ font-family: var(--mono); }}

footer {{ text-align: center; color: var(--muted); font-size: 0.78em;
  padding: 20px; border-top: 1px solid var(--border); margin-top: 32px; }}
</style>
</head>
<body>
<header>
  <h1><span class="status-dot"></span>Raftel AE Report</h1>
  <span class="run-meta">
    {run_id} &nbsp;·&nbsp;
    <a href="{git_url}" style="color:var(--accent);text-decoration:none;">{git_commit_short}</a>
    &nbsp;·&nbsp; {started_fmt}{(' → ' + finished_fmt) if finished_fmt != '—' else ''}
    {(' &nbsp;·&nbsp; ' + duration) if duration else ''}
    &nbsp;·&nbsp; Generated {now}
  </span>
</header>
<main>

  <!-- Claim summary cards -->
  <div class="claim-cards">
    {claim_cards_html}
  </div>

  <!-- Figure sections -->
  {fig_sections_html}

  <!-- Audit section -->
  <div class="audit-section">
    <h2>Experiment audit trail</h2>
    <div class="audit-grid">
      <div class="audit-block">
        <h3>Run metadata</h3>
        <div class="audit-row"><span class="key">Run ID</span> <span class="mono">{run_id}</span></div>
        <div class="audit-row"><span class="key">Git commit</span>
          <a href="{git_url}" target="_blank">{git_commit_short}</a>
          <span class="muted" style="font-size:0.85em"> — click to verify code snapshot</span>
        </div>
        <div class="audit-row"><span class="key">Scale</span> {scale}</div>
        <div class="audit-row"><span class="key">Started</span> {started_fmt}</div>
        <div class="audit-row"><span class="key">Finished</span> {finished_fmt}</div>
        <div class="audit-row"><span class="key">Duration</span> {duration or '—'}</div>
        <div class="audit-row"><span class="key">Cluster nodes</span>
          {len(cluster_ips)} host(s): {ip_list_html}
        </div>
        <div class="audit-row"><span class="key">Failed exps</span>
          {', '.join(failed_figs) if failed_figs else 'none'}
        </div>
      </div>
      <div class="audit-block">
        <h3>Event timeline</h3>
        {events_html}
      </div>
    </div>
    <div style="margin-top:20px">
      <h3 style="font-size:0.82em;font-weight:600;text-transform:uppercase;
                 letter-spacing:0.05em;color:var(--muted);margin-bottom:8px;">
        Script integrity (SHA-256)
      </h3>
      {checksums_html}
    </div>
  </div>

</main>
<footer>Raftel Artifact Evaluation &nbsp;·&nbsp; {run_id}</footer>
</body>
</html>
"""


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <run_dir>", file=sys.stderr)
        sys.exit(1)
    run_dir = Path(sys.argv[1])
    if not run_dir.exists():
        print(f"Run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    # Run plot scripts first
    import os
    EXP_MAP = {"fig3": "experiment1", "fig4": "experiment2", "fig6": "experiment3"}
    for fig, exp in EXP_MAP.items():
        plot_script = REPO / "scripts" / f"plot_{fig}.py"
        if plot_script.exists():
            stats_file = run_dir / "stats" / f"{fig}.txt"
            if stats_file.exists():
                env = os.environ.copy()
                env["AE_RUN_DIR"] = str(run_dir)
                env["AE_STATS_FILE"] = str(stats_file)
                rc = subprocess.call([sys.executable, str(plot_script)], env=env)
                if rc != 0:
                    print(f"Plot generation failed for {fig} (exit {rc})", file=sys.stderr)

    html = build_report(run_dir)
    out = run_dir / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"Report written: {out}")


if __name__ == "__main__":
    main()
