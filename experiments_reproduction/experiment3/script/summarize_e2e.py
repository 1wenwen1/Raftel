#!/usr/bin/env python3
import argparse
import csv
import glob
import statistics
from pathlib import Path


METRICS = (
    "e2e_throughput_ktps",
    "e2e_latency_avg_ms",
    "e2e_latency_p50_ms",
    "e2e_latency_p95_ms",
    "e2e_latency_p99_ms",
    "num_completed",
)


def read_run(stats_dir: Path):
    clients = []
    for filename in glob.glob(str(stats_dir / "client-e2e-*")):
        values = {}
        with open(filename, encoding="utf-8") as source:
            for line in source:
                fields = line.split()
                if len(fields) >= 2:
                    try:
                        values[fields[0]] = float(fields[1])
                    except ValueError:
                        pass
        if values:
            clients.append(values)
    if not clients:
        raise RuntimeError(f"no client-e2e-* files found under {stats_dir}")

    required_window = ("num_completed", "first_reply_unix_us", "last_reply_unix_us")
    if not all(all(key in client for key in required_window) for client in clients):
        raise RuntimeError("client E2E files lack completion/reply-window fields")
    completed = sum(client["num_completed"] for client in clients)
    first_us = min(client["first_reply_unix_us"] for client in clients)
    last_us = max(client["last_reply_unix_us"] for client in clients)
    window_sec = (last_us - first_us) / 1_000_000.0
    throughput = completed / window_sec / 1000.0 if window_sec > 0 else 0.0

    def mean(key):
        values = [client[key] for client in clients if key in client]
        return statistics.fmean(values) if values else 0.0

    return {
        "e2e_throughput_ktps": throughput,
        "e2e_latency_avg_ms": mean("e2e_latency_avg_ms"),
        "e2e_latency_p50_ms": mean("e2e_latency_p50_ms"),
        "e2e_latency_p95_ms": mean("e2e_latency_p95_ms"),
        "e2e_latency_p99_ms": mean("e2e_latency_p99_ms"),
        "num_completed": completed,
    }


def aggregate(per_run_csv: Path, summary_csv: Path):
    grouped = {}
    with open(per_run_csv, newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            if row["status"] != "success":
                continue
            grouped.setdefault(row["protocol"], []).append(row)

    with open(summary_csv, "w", newline="", encoding="utf-8") as target:
        writer = csv.writer(target)
        writer.writerow(("protocol", "successful_repeats", *METRICS))
        for protocol in sorted(grouped):
            rows = grouped[protocol]
            writer.writerow((
                protocol,
                len(rows),
                *(statistics.fmean(float(row[key]) for row in rows) for key in METRICS),
            ))


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("stats_dir", type=Path)
    aggregate_parser = subparsers.add_parser("aggregate")
    aggregate_parser.add_argument("per_run_csv", type=Path)
    aggregate_parser.add_argument("summary_csv", type=Path)
    args = parser.parse_args()

    if args.command == "run":
        result = read_run(args.stats_dir)
        print(",".join(str(result[key]) for key in METRICS))
    else:
        aggregate(args.per_run_csv, args.summary_csv)


if __name__ == "__main__":
    main()
