import json
from pathlib import Path
from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.acs_exception.exceptions import ServerException
from aliyunsdkcore.request import CommonRequest

ALIYUN_DIR = Path(__file__).resolve().parent

# Read the configuration file
with (ALIYUN_DIR / "config.json").open("r") as f:
    config = json.load(f)

region_id = config["region_id"]
access_key_id = config["access_key_id"]
access_key_secret = config["access_key_secret"]

# Read the list of instance IDs
instance_ids = []
with (ALIYUN_DIR / "instances.txt").open("r") as f:
    for line in f:
        if line.strip():  # Make sure that the line is not empty.
            instance_ids.append(line.strip())

# Get the private network IP of each instance and save it to the file
with (ALIYUN_DIR / "priv_ip.txt").open("w") as f:
    for instance_id in instance_ids:
        client = AcsClient(access_key_id, access_key_secret, region_id)

        request = CommonRequest()
        request.set_accept_format('json')
        request.set_domain('ecs.aliyuncs.com')
        request.set_method('POST')
        request.set_protocol_type('https')
        request.set_version('2014-05-26')
        request.set_action_name('DescribeInstanceAttribute')

        request.add_query_param('InstanceId', instance_id)

        try:
            response = client.do_action_with_exception(request)
            result = json.loads(response.decode('utf-8'))
            private_ip = result["VpcAttributes"]["PrivateIpAddress"]["IpAddress"][0]
            f.write(f"{private_ip}\n")
        except ServerException as e:
            print(f"Error getting private IP for instance {instance_id}: {e}")

# with open("pub_ip.txt", "w") as f:
#     for instance_id in instance_ids:
#         client = AcsClient(access_key_id, access_key_secret, region_id)
#
#         request = CommonRequest()
#         request.set_accept_format('json')
#         request.set_domain('ecs.aliyuncs.com')
#         request.set_method('POST')
#         request.set_protocol_type('https')
#         request.set_version('2014-05-26')
#         request.set_action_name('DescribeInstanceAttribute')
#
#         request.add_query_param('InstanceId', instance_id)
#
#         try:
#             response = client.do_action_with_exception(request)
#             result = json.loads(response.decode('utf-8'))
#             private_ip = result["VpcAttributes"]["PublicIpAddress"]["IpAddress"][0]
#             f.write(f"{private_ip}\n")
#         except ServerException as e:
#             print(f"Error getting private IP for instance {instance_id}: {e}")
# with open("instances.txt", "w") as f:
#     pass
