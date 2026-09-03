#!/usr/bin/env python3
"""
Pull server stdout logs (out0, out1, ...) from ECS nodes after cloud experiments.

Remote paths match run.py: ssh_exec_server redirects ./sgxserver ... > out{id}
under DAMYSUS_REMOTE_ROOT (default: same repo path as locally).

IP sources (first non-empty wins):
  1) <repo>/ip_list   — same as mkConfig / run.py scp targets
  2) aliyun/priv_ip.txt

Usage:
  python3 deployment/fetch_remote_logs.py
  python3 deployment/fetch_remote_logs.py --out out/run1
  DAMYSUS_REMOTE_ROOT=/root/Raftel python3 deployment/fetch_remote_logs.py
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _read_ips(project_root: Path) -> list[str]:
    for rel in ("ip_list", "aliyun/priv_ip.txt"):
        p = project_root / rel
        if not p.is_file():
            continue
        ips = [ln.strip() for ln in p.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
        if ips:
            return sorted(set(ips))
    return []


def _ssh_ls_remote_out_files(key: Path, ip: str, remote_root: str) -> list[str]:
    """Return remote absolute paths for out* log files (no glob over scp — avoids 'Not a directory')."""
    script = f"ls -1 {remote_root}/out[0-9]* 2>/dev/null || ls -1 {remote_root}/out* 2>/dev/null || true"
    cmd = [
        "ssh",
        "-i",
        str(key),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "BatchMode=yes",
        f"root@{ip}",
        "bash",
        "-lc",
        script,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return []
    paths = []
    for line in r.stdout.splitlines():
        p = line.strip()
        if p and p.startswith("/"):
            paths.append(p)
    return paths


def _scp_one_remote_file(key: Path, ip: str, remote_file: str, dest_dir: Path) -> bool:
    dest_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "scp",
        "-i",
        str(key),
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "BatchMode=yes",
        f"root@{ip}:{remote_file}",
        str(dest_dir) + os.sep,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode == 0


def _fetch_ip_logs(key: Path, ip: str, remote_root: str, dest_dir: Path) -> int:
    """
    Returns number of files copied (0 = nothing found / all scp failed).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    remote_paths = _ssh_ls_remote_out_files(key, ip, remote_root)
    if not remote_paths:
        # Fallback: try fixed replica ids (run.py uses id 0..3f)
        got = 0
        for rid in range(32):
            rf = f"{remote_root}/out{rid}"
            if _scp_one_remote_file(key, ip, rf, dest_dir):
                got += 1
        if got == 0:
            sys.stderr.write(
                f"[{ip}] no remote log files under {remote_root}/out<N> "
                f"(experiment not run yet, wrong --remote-root, or logs elsewhere).\n"
            )
        else:
            print(f"[{ip}] copied {got} file(s) -> {dest_dir}")
        return got

    got = 0
    for rf in remote_paths:
        if _scp_one_remote_file(key, ip, rf, dest_dir):
            got += 1
    if got:
        print(f"[{ip}] copied {got} file(s) -> {dest_dir}")
    else:
        sys.stderr.write(f"[{ip}] listed {len(remote_paths)} path(s) but scp failed for all.\n")
    return got


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    default_remote = os.environ.get("DAMYSUS_REMOTE_ROOT", str(project_root))
    key = project_root / "TShard"

    parser = argparse.ArgumentParser(
        description="Fetch remote sgxserver logs (out0, out1, ...) from cluster nodes."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=project_root / "out",
        help="Local directory to write into (per-node subdirs by IP)",
    )
    parser.add_argument(
        "--remote-root",
        type=str,
        default=default_remote,
        help="Remote project root (same as DAMYSUS_REMOTE_ROOT in run.py)",
    )
    parser.add_argument(
        "--key",
        type=Path,
        default=key,
        help="SSH private key path",
    )
    args = parser.parse_args()

    if not args.key.is_file():
        print(f"SSH key not found: {args.key}", file=sys.stderr)
        return 1

    ips = _read_ips(project_root)
    if not ips:
        print("No IPs found in ip_list or aliyun/priv_ip.txt", file=sys.stderr)
        return 1

    remote_root = args.remote_root.rstrip("/")
    out_base: Path = args.out
    out_base.mkdir(parents=True, exist_ok=True)

    empty_ips = 0
    for ip in ips:
        dest = out_base / ip.replace(".", "_")
        n = _fetch_ip_logs(args.key, ip, remote_root, dest)
        if n == 0:
            empty_ips += 1

    print(f"Done. IPs={len(ips)}, nodes_with_no_logs={empty_ips}, local base={out_base}")
    return 1 if empty_ips == len(ips) else 0


if __name__ == "__main__":
    sys.exit(main())
