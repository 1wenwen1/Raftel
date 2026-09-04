#!/usr/bin/env python3
"""Wait until all listed ECS instances are running, have private IPs, and accept SSH."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.acs_exception.exceptions import ClientException, ServerException
from aliyunsdkcore.request import CommonRequest


ALIYUN_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ALIYUN_DIR.parent


def read_nonempty_lines(path: Path) -> List[str]:
    if not path.is_file():
        raise FileNotFoundError(f"required file not found: {path}")
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def describe_instance(client: AcsClient, instance_id: str) -> Tuple[str, Optional[str]]:
    request = CommonRequest()
    request.set_accept_format("json")
    request.set_domain("ecs.aliyuncs.com")
    request.set_method("POST")
    request.set_protocol_type("https")
    request.set_version("2014-05-26")
    request.set_action_name("DescribeInstanceAttribute")
    request.add_query_param("InstanceId", instance_id)

    response = client.do_action_with_exception(request)
    if response is None:
        raise RuntimeError(
            f"Ali Cloud returned an empty response for instance {instance_id}"
        )
    result = json.loads(response.decode("utf-8"))
    status = result.get("Status", "Unknown")
    private_ips = (
        result.get("VpcAttributes", {})
        .get("PrivateIpAddress", {})
        .get("IpAddress", [])
    )
    private_ip = private_ips[0] if private_ips else None
    return status, private_ip


def ssh_is_ready(ip: str, user: str, key: Path, connect_timeout: int) -> bool:
    command = [
        "ssh",
        "-i",
        str(key),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        f"ConnectTimeout={connect_timeout}",
        f"{user}@{ip}",
        "true",
    ]
    result = subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=10.0, help="poll interval in seconds")
    parser.add_argument("--timeout", type=float, default=900.0, help="overall timeout in seconds")
    parser.add_argument("--connect-timeout", type=int, default=5, help="SSH connection timeout in seconds")
    parser.add_argument("--key", type=Path, default=PROJECT_ROOT / "TShard", help="SSH private key")
    parser.add_argument("--user", default="root", help="SSH user")
    args = parser.parse_args()

    if args.interval <= 0 or args.timeout <= 0 or args.connect_timeout <= 0:
        parser.error("timeouts and polling interval must be positive")
    if not args.key.is_file():
        parser.error(f"SSH private key not found: {args.key}")

    try:
        instance_ids = read_nonempty_lines(ALIYUN_DIR / "instances.txt")
        config = json.loads((ALIYUN_DIR / "config.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if not instance_ids:
        print("ERROR: aliyun/instances.txt contains no instance IDs", file=sys.stderr)
        return 1

    try:
        client = AcsClient(
            config["access_key_id"],
            config["access_key_secret"],
            config["region_id"],
        )
    except KeyError as exc:
        print(f"ERROR: missing config key: {exc}", file=sys.stderr)
        return 1
    deadline = time.monotonic() + args.timeout

    while True:
        ready_ips: List[str] = []
        all_ready = True
        for instance_id in instance_ids:
            try:
                status, private_ip = describe_instance(client, instance_id)
            except (
                ClientException,
                ServerException,
                RuntimeError,
                KeyError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                print(f"[{instance_id}] ECS query failed: {exc}")
                all_ready = False
                continue

            ssh_ready = False
            if status == "Running" and private_ip:
                ssh_ready = ssh_is_ready(private_ip, args.user, args.key, args.connect_timeout)
            print(
                f"[{instance_id}] status={status} "
                f"private_ip={private_ip or '-'} ssh={'ready' if ssh_ready else 'waiting'}"
            )
            if status == "Running" and private_ip and ssh_ready:
                ready_ips.append(private_ip)
            else:
                all_ready = False

        if all_ready and len(ready_ips) == len(instance_ids):
            output = ALIYUN_DIR / "priv_ip.txt"
            temporary = output.with_suffix(".txt.tmp")
            temporary.write_text("".join(f"{ip}\n" for ip in ready_ips))
            temporary.replace(output)
            print(f"All {len(ready_ips)} instances are ready; wrote {output}")
            return 0

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print("ERROR: timed out before all instances became ready", file=sys.stderr)
            return 1
        print(f"Waiting {min(args.interval, remaining):.1f}s before the next check...", flush=True)
        time.sleep(min(args.interval, remaining))


if __name__ == "__main__":
    sys.exit(main())
