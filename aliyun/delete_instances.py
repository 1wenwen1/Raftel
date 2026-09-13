import sys
from pathlib import Path
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.acs_exception.exceptions import ClientException, ServerException
from aliyunsdkcore.request import CommonRequest

from cloud_common import ALIYUN_DIR, load_config

config = load_config()

region_id = config["region_id"]
access_key_id = config["access_key_id"]
access_key_secret = config["access_key_secret"]

# Read the list of instance IDs
instances_file = ALIYUN_DIR / "instances.txt"
instance_ids = []
with instances_file.open("r") as f:
    for line in f:
        if line.strip():  # Make sure that the line is not empty.
            instance_ids.append(line.strip())

# The coordinator is developer-owned and tracked separately. Refuse to delete
# it even if an old setup accidentally left its ID in the replica ledger.
runner_path = ALIYUN_DIR / "runner.json"
runner_id = None
if runner_path.is_file():
    import json
    runner_id = json.loads(runner_path.read_text()).get("instance_id")
if runner_id in instance_ids:
    instance_ids = [instance_id for instance_id in instance_ids if instance_id != runner_id]
    save_text = "".join(f"{instance_id}\n" for instance_id in instance_ids)
    instances_file.write_text(save_text)


def save_remaining_instance_ids(instance_ids):
    """Atomically update instances.txt with IDs that still need deletion."""
    temporary_file = instances_file.with_suffix(".txt.tmp")
    temporary_file.write_text(
        "".join(f"{instance_id}\n" for instance_id in instance_ids)
    )
    temporary_file.replace(instances_file)


# Delete each instance
client = AcsClient(access_key_id, access_key_secret, region_id)
remaining_instance_ids = instance_ids.copy()

for instance_id in instance_ids:

    request = CommonRequest()
    request.set_accept_format('json')
    request.set_domain('ecs.aliyuncs.com')
    request.set_method('POST')
    request.set_protocol_type('https')
    request.set_version('2014-05-26')
    request.set_action_name('DeleteInstance')
    request.add_query_param('InstanceId', instance_id)
    # request.add_query_param('TerminateSubscription', 'true')  # Release resources and delete them
    request.add_query_param('Force', 'true')

    try:
        response = client.do_action_with_exception(request)
        print(f"Instance {instance_id} deleted successfully.")
        remaining_instance_ids = [
            remaining_id
            for remaining_id in remaining_instance_ids
            if remaining_id != instance_id
        ]
        save_remaining_instance_ids(remaining_instance_ids)
    except (ClientException, ServerException) as e:
        print(f"Error deleting instance {instance_id}: {e}", file=sys.stderr)

if remaining_instance_ids:
    raise SystemExit(1)

for name in (
    # runner.json is the developer-owned coordinator identity and must survive
    # release of a disposable replica-only cluster.
    "cluster_plan.json", "hosts.json", "priv_ip.txt", "public_ip.txt"
):
    path = ALIYUN_DIR / name
    if path.exists():
        path.unlink()
