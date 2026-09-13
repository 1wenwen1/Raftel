"""Bounded SSH checks with raw evidence; presence checks are not attestation."""
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import shlex
import sys

REPO = __import__("pathlib").Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "aliyun"))
from cloud_common import ssh_address
from cloud_common import read_inventory

CHECK=r'''set -eu
. /etc/os-release
printf 'os:%s:%s\n' "$ID" "$VERSION_ID"
test "$ID:$VERSION_ID" = ubuntu:20.04
test "$(uname -m)" = x86_64
printf 'cpu:%s\n' "$(nproc)"
test "$(nproc)" -ge 8
# g7t.2xlarge has 32 GiB total RAM; roughly 16 GiB is reserved as SGX EPC and
# therefore absent from Linux MemTotal. The ECS inventory separately fixes the
# instance type; require the expected remaining host memory here.
awk '/MemTotal/ {print "host_memory_after_epc_kb:" $2; if ($2 < 15000000) exit 1}' /proc/meminfo
dmesg | grep -i 'sgx: EPC section'
for device in /dev/sgx_enclave /dev/sgx_provision; do test -c "$device"; ls -l "$device"; done
test -f /opt/intel/sgxsdk/environment
test -x /opt/intel/sgxsdk/bin/x64/sgx_sign
test -f /opt/intel/sgxssl/include/sgx_tsgxssl.edl
test -f /opt/intel/sgxssl/include/tSgxSSL_api.h
ldconfig -p | grep 'libsgx_urts.so'
command -v redis-server
pkg-config --exists hiredis
find /root/Raftel/salticidae -name 'libsalticidae.a' -print | grep .
test -f /root/Raftel/salticidae/include/salticidae/network.h
command -v tc
uname -a
cpuid -1 -l 0x7 | grep -qi 'SGX:.*true'
cpuid -1 -l 0x7 | grep -qi 'SGX_LC:.*true'
sample=/opt/intel/sgxsdk/SampleCode/SampleEnclave
test -d "$sample"
(cd "$sample" && make clean >/dev/null && make SGX_MODE=HW SGX_DEBUG=1 >/dev/null)
(cd "$sample" && printf 'x\n' | ./app) | tee /tmp/raftel-sgx-sample.log
grep -q 'SampleEnclave successfully returned' /tmp/raftel-sgx-sample.log
printf 'CHECK_COMPLETE\n'
'''


def check_cluster(ips,key,output, profile="paper"):
 inventory = {h.get("private_ip"): h for h in read_inventory()}
 metadata_errors = []
 for ip in ips:
  host = inventory.get(ip, {})
  instance_type = host.get("instance_type") if host else None
  allowed = instance_type == "ecs.g7t.2xlarge" or (
      profile == "simulation" and isinstance(instance_type, str) and instance_type.startswith("ecs.g7t.")
  )
  if host and not allowed:
   metadata_errors.append(f"{ip}: instance type is {host.get('instance_type')}")
  if host and host.get("image_id") is None:
   metadata_errors.append(f"{ip}: missing image metadata")
 if metadata_errors:
  for error in metadata_errors: print(f"METADATA FAIL: {error}")
  return 1
 def one(ip):
  try:
   target = ssh_address(ip)
   r=subprocess.run(['ssh','-i',str(key),'-o','BatchMode=yes','-o','ConnectTimeout=10','-o','StrictHostKeyChecking=accept-new',f'root@{target}','bash -c '+shlex.quote(CHECK)],capture_output=True,text=True,timeout=180)
   return {'private_ip':ip,'ssh_address':target,'ok':r.returncode==0 and 'CHECK_COMPLETE' in r.stdout.splitlines(),'exit':r.returncode,'stdout':r.stdout,'stderr':r.stderr}
  except (subprocess.TimeoutExpired,OSError) as exc:return {'ip':ip,'ok':False,'error':str(exc)}
 results=[]
 with ThreadPoolExecutor(max_workers=12) as pool:
  for f in as_completed([pool.submit(one,ip) for ip in ips]):
   item=f.result();results.append(item)
   print(f"[{len(results)}/{len(ips)}] {item.get('private_ip', item.get('ip'))}: {'OK' if item['ok'] else 'FAIL'}",flush=True)
   if not item['ok']:print(item.get('stderr') or item.get('error') or item.get('stdout',''))
 output.parent.mkdir(parents=True,exist_ok=True)
 verified = bool(results) and all(r['ok'] for r in results)
 output.write_text(json.dumps({'checked_at':datetime.now(timezone.utc).isoformat(),'kind':'hardware-and-dependency-preflight','hardware_execution_verified':verified,'remote_attestation_performed':False,'hosts':results},indent=2)+'\n')
 return 0 if results and all(r['ok'] for r in results) else 1
