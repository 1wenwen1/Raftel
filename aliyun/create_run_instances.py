import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.acs_exception.exceptions import ClientException, ServerException
from aliyunsdkcore.request import CommonRequest

from cloud_common import ALIYUN_DIR, load_config

config = load_config()

region_id = config["region_id"]
access_key_id = config["access_key_id"]
access_key_secret = config["access_key_secret"]
# AE FIX: cloud up --count must actually control the billed instance count.
parser = argparse.ArgumentParser()
parser.add_argument("--count", type=int)
parser.add_argument("--profile", choices=("paper", "simulation"), default="paper", help=argparse.SUPPRESS)
parser.add_argument(
    "--no-runner",
    action="store_true",
    help="create replica hosts only; use when this command runs on an existing coordinator",
)
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()
instance_type = config["instance_type"]
replica_count = args.count if args.count is not None else config["instance_count"]
runner_count = 1 if (not args.no_runner and config.get("use_cloud_runner", True) and replica_count > 1) else 0
instance_count = replica_count + runner_count
if not 1 <= replica_count <= 97 or instance_count > 100:
    parser.error("replica count must be between 1 and 97 (plus at most one runner)")
if instance_type != "ecs.g7t.2xlarge":
    parser.error("paper profile requires ecs.g7t.2xlarge")
existing = ALIYUN_DIR / "instances.txt"
if not args.dry_run and existing.exists() and existing.read_text().strip():
    parser.error("instances.txt already tracks a cluster; reuse it or release it before provisioning")
image_id = config["image_id"]
security_group_id = config["security_group_id"]
instance_name_prefix = config["instance_name_prefix"]
key_pair_name = config["key_pair_name"]
vpc_id = config["vpc_id"]
vswitch_id = config["vswitch_id"]

# Create an ECS instance function
def create_ecs_instances():
    client = AcsClient(access_key_id, access_key_secret, region_id)
    candidates = [instance_type]
    release_hours = float(config.get("auto_release_hours", 8))
    if not 0.5 <= release_hours <= 24:
        raise ValueError("auto_release_hours must be between 0.5 and 24")
    auto_release = datetime.now(timezone.utc) + timedelta(hours=release_hours)
    response = None
    selected_type = instance_type
    last_error = None
    for candidate in candidates:
        request = CommonRequest()
        request.set_accept_format('json')
        request.set_domain('ecs.aliyuncs.com')
        request.set_method('POST')
        request.set_protocol_type('https')
        request.set_version('2014-05-26')
        request.set_action_name('RunInstances')
        request.add_query_param('InstanceType', candidate)
        request.add_query_param('ImageId', image_id)
        request.add_query_param('RegionId', region_id)
        request.add_query_param('SecurityGroupId', security_group_id)
        request.add_query_param('InstanceName', instance_name_prefix)
        request.add_query_param('InternetMaxBandwidthOut', str(config.get('internet_max_bandwidth_out', 100)))
        request.add_query_param('SystemDisk.Category', 'cloud_essd')
        request.add_query_param('VpcId', vpc_id)
        request.add_query_param('VSwitchId', vswitch_id)
        request.add_query_param('InstanceChargeType', 'PostPaid')
        request.add_query_param('KeyPairName', key_pair_name)
        request.add_query_param('SecurityOptions.TrustedSystemMode', 'vTPM')
        request.add_query_param('UniqueSuffix', 'true')
        request.add_query_param('AutoReleaseTime', auto_release.strftime('%Y-%m-%dT%H:%M:%SZ'))
        request.add_query_param('Tag.1.Key', 'raftel-ae')
        request.add_query_param('Tag.1.Value', '20260912')
        request.add_query_param('Amount', instance_count)
        if args.dry_run:
            request.add_query_param('DryRun', 'true')
        print(
            f"Plan: region={region_id}, type={candidate}, replicas={replica_count}, "
            f"runner={runner_count}, total={instance_count}, auto_release={auto_release.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )
        try:
            response = client.do_action_with_exception(request)
            selected_type = candidate
            break
        except ServerException as exc:
            last_error = exc
            if args.dry_run and exc.get_error_code() == "DryRunOperation":
                print("Dry-run passed: credentials, permissions, parameters, quota and stock accepted.")
                return
            raise RuntimeError(f"Error creating instances: {exc}") from exc
    if response is None:
        raise RuntimeError(f"No SGX instance type has stock in {region_id}: {last_error}")
    instance_ids = json.loads(response.decode('utf-8'))["InstanceIdSets"]["InstanceIdSet"]
    if len(instance_ids) != instance_count:
        raise RuntimeError(
            f"ECS returned {len(instance_ids)} IDs for {instance_count} requested instances"
        )
    with (ALIYUN_DIR / "instances.txt").open("a") as f:
        for instance_id in instance_ids:
            f.write(f"{instance_id}\n")
    plan = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "auto_release_at": auto_release.isoformat(),
        "region_id": region_id,
        "instance_type": selected_type,
        "image_id": image_id,
        "replica_count": replica_count,
        "runner_count": runner_count,
        "runner_instance_ids": instance_ids[:runner_count],
        "replica_instance_ids": instance_ids[runner_count:],
    }
    (ALIYUN_DIR / "cluster_plan.json").write_text(
        json.dumps(plan, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"Created {replica_count} replica host(s) and {runner_count} runner; "
        f"automatic release at {plan['auto_release_at']}"
    )

# Create an instance
create_ecs_instances()
