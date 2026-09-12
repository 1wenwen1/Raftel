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

from cloud_common import ALIYUN_DIR, PROJECT_ROOT, load_config, ssh_key



def read_nonempty_lines(path: Path) -> List[str]:
    if not path.is_file():
        raise FileNotFoundError(f"required file not found: {path}")
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def describe_instance(client: AcsClient, instance_id: str) -> dict:
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
    public_ips = result.get("PublicIpAddress", {}).get("IpAddress", [])
    eip = result.get("EipAddress", {}).get("IpAddress")
    public_ip = public_ips[0] if public_ips else (eip or None)
    return {
        "instance_id": instance_id,
        "status": status,
        "private_ip": private_ip,
        "public_ip": public_ip,
        "instance_type": result.get("InstanceType"),
        "image_id": result.get("ImageId"),
        "region_id": result.get("RegionId"),
        "zone_id": result.get("ZoneId"),
        "creation_time": result.get("CreationTime"),
    }


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
    parser.add_argument("--key", type=Path, default=None, help="SSH private key override")
    parser.add_argument("--user", default="root", help="SSH user")
    args = parser.parse_args()

    if args.interval <= 0 or args.timeout <= 0 or args.connect_timeout <= 0:
        parser.error("timeouts and polling interval must be positive")

    try:
        instance_ids = read_nonempty_lines(ALIYUN_DIR / "instances.txt")
        config = load_config()
        plan = json.loads((ALIYUN_DIR / "cluster_plan.json").read_text())
    except (FileNotFoundError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    args.key = (args.key or ssh_key(config)).resolve()
    if not args.key.is_file():
        parser.error(f"SSH private key not found: {args.key}")
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
        ready_hosts: List[dict] = []
        all_ready = True
        for instance_id in instance_ids:
            try:
                host = describe_instance(client, instance_id)
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
            if host["status"] == "Running" and host["public_ip"]:
                ssh_ready = ssh_is_ready(
                    host["public_ip"], args.user, args.key, args.connect_timeout
                )
            print(
                f"[{instance_id}] status={host['status']} "
                f"private_ip={host['private_ip'] or '-'} "
                f"public_ip={host['public_ip'] or '-'} "
                f"ssh={'ready' if ssh_ready else 'waiting'}"
            )
            if (
                host["status"] == "Running"
                and host["private_ip"]
                and host["public_ip"]
                and ssh_ready
            ):
                host["role"] = (
                    "runner"
                    if instance_id in plan.get("runner_instance_ids", [])
                    else "replica"
                )
                ready_hosts.append(host)
            else:
                all_ready = False

        if all_ready and len(ready_hosts) == len(instance_ids):
            ordered = sorted(
                ready_hosts,
                key=lambda h: (h["role"] != "runner", instance_ids.index(h["instance_id"])),
            )
            inventory = ALIYUN_DIR / "hosts.json"
            inventory.write_text(json.dumps(ordered, indent=2) + "\n")
            replicas = [h for h in ordered if h["role"] == "replica"]
            runners = [h for h in ordered if h["role"] == "runner"]
            (ALIYUN_DIR / "priv_ip.txt").write_text(
                "".join(f"{h['private_ip']}\n" for h in replicas)
            )
            (ALIYUN_DIR / "public_ip.txt").write_text(
                "".join(f"{h['public_ip']}\n" for h in ordered)
            )
            (ALIYUN_DIR / "runner.json").write_text(
                json.dumps(runners[0] if runners else {}, indent=2) + "\n"
            )
            print(
                f"All {len(ordered)} instances are ready: "
                f"{len(replicas)} replica(s), {len(runners)} runner"
            )
            return 0

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print("ERROR: timed out before all instances became ready", file=sys.stderr)
            return 1
        print(f"Waiting {min(args.interval, remaining):.1f}s before the next check...", flush=True)
        time.sleep(min(args.interval, remaining))


if __name__ == "__main__":
    sys.exit(main())
