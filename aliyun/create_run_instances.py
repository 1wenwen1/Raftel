import argparse
import json
import sys
from pathlib import Path
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.acs_exception.exceptions import ServerException
from aliyunsdkcore.request import CommonRequest

# Read files relative to this script so the repository can live at any path.
ALIYUN_DIR = Path(__file__).resolve().parent

with (ALIYUN_DIR / "config.json").open("r") as f:
    config = json.load(f)

region_id = config["region_id"]
access_key_id = config["access_key_id"]
access_key_secret = config["access_key_secret"]
instance_type = config["instance_type"]
instance_count = config["instance_count"]
image_id = config["image_id"]
security_group_id = config["security_group_id"]
instance_name_prefix = config["instance_name_prefix"]
key_pair_name = config["key_pair_name"]
vpc_id = config["vpc_id"]
vswitch_id = config["vswitch_id"]

# Create an ECS instance function
def create_ecs_instances(count=None):
    client = AcsClient(access_key_id, access_key_secret, region_id)

    request = CommonRequest()
    request.set_accept_format('json')
    request.set_domain('ecs.aliyuncs.com')
    request.set_method('POST')
    request.set_protocol_type('https')
    request.set_version('2014-05-26')
    request.set_action_name('RunInstances')

    request.add_query_param('InstanceType', instance_type)
    request.add_query_param('ImageId', image_id)
    request.add_query_param('RegionId', region_id)
    request.add_query_param('SecurityGroupId', security_group_id)
    request.add_query_param('InstanceName', instance_name_prefix)
    request.add_query_param('InternetMaxBandwidthOut', '100')  # Pay as you use
    request.add_query_param('SystemDisk.Category', 'cloud_essd')
    request.add_query_param('VpcId', vpc_id)
    request.add_query_param('VSwitchId', vswitch_id)
    request.add_query_param('InstanceChargeType', 'PostPaid')  # Pay by volume
    request.add_query_param('KeyPairName', key_pair_name)  # Set the key pair
    request.add_query_param('SecurityOptions.TrustedSystemMode', 'vTPM')
    request.add_query_param('UniqueSuffix', 'true')  # Set an orderly instance name
    # request.add_query_param('AutoReleaseTime', '2024-06-01T12:00:00Z')  # Automatic release time
    request.add_query_param('Amount', count if count is not None else instance_count)

    try:
        response = client.do_action_with_exception(request)
        print("Instances created successfully.")
        if response is None:
            print("Error: No response received from the server")
            return 1
        instance_ids = json.loads(response.decode('utf-8'))["InstanceIdSets"]["InstanceIdSet"]
        # Save the instance ID to the file
        with (ALIYUN_DIR / "instances.txt").open("a") as f:
            for instance_id in instance_ids:
                f.write(f"{instance_id}\n")
    except ServerException as e:
        print(f"Error creating instances: {e}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create Raftel ECS instances")
    parser.add_argument("--count", type=int, default=None,
                        help="override instance_count from config.json")
    args = parser.parse_args()
    if args.count is not None and args.count < 1:
        parser.error("--count must be at least 1")
    sys.exit(create_ecs_instances(args.count))
