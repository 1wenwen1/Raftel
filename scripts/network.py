#!/usr/bin/env python3
"""Apply/verify experiment networking; every SSH or tc error is fatal."""
import argparse
import json
import os
import shlex
import subprocess
import re
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime,timezone
from pathlib import Path
REPO=Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'aliyun'))
from cloud_common import ssh_address, ssh_key


def ping_samples(output):
 values=[float(value) for value in re.findall(r'time[=<]([\d.]+)\s*ms',output)]
 if not values:
  raise ValueError('no RTT samples found')
 return values


def delay_seconds(value):
 """Normalize tc JSON delay values such as ``50ms`` or ``0.05``."""
 if isinstance(value,(int,float)):
  return float(value)
 if isinstance(value,str):
  match=re.fullmatch(r'\s*([0-9]+(?:\.[0-9]+)?)\s*(ns|us|ms|s)?\s*',value)
  if not match:return None
  amount=float(match.group(1));unit=match.group(2) or 's'
  return amount*{'ns':1e-9,'us':1e-6,'ms':1e-3,'s':1}[unit]
 return None


def netem_delay_seconds(entry):
 """Extract a netem delay regardless of tc JSON's string/object shape."""
 options=entry.get('options',{}) if isinstance(entry,dict) else {}
 value=options.get('delay') if isinstance(options,dict) else None
 if isinstance(value,dict):value=value.get('delay')
 return delay_seconds(value)


def configure(mode,ips):
 def host(ip):
  peer=next((p for p in ips if p!=ip),None)
  if peer is None:raise RuntimeError('At least two distinct hosts are required')
  script='''set -eu
iface=$(ip -o route get PEER | awk '{for(i=1;i<=NF;i++) if($i=="dev") {print $(i+1); exit}}')
test -n "$iface"
'''.replace('PEER',shlex.quote(peer))
  if mode=='wan':script+='sudo tc qdisc replace dev "$iface" root netem delay 50ms\n'
  else:script+='''if tc qdisc show dev "$iface" | grep -q 'qdisc netem .* root'; then
 sudo tc qdisc del dev "$iface" root
fi
if tc qdisc show dev "$iface" | grep -q 'netem'; then echo "ERROR: residual netem" >&2; exit 1; fi
'''
  script+='tc -j qdisc show dev "$iface"\n'
  r=subprocess.run(['ssh','-i',str(ssh_key()),'-o','BatchMode=yes','-o','ConnectTimeout=10','-o','StrictHostKeyChecking=accept-new',f'root@{ssh_address(ip)}','bash -c '+shlex.quote(script)],capture_output=True,text=True,timeout=40)
  if r.returncode:raise RuntimeError(f'{mode} configuration failed on {ip}: {r.stderr or r.stdout}')
  qdisc=json.loads(r.stdout)
  netem=[entry for entry in qdisc if entry.get('kind')=='netem']
  if mode=='wan':
   delays=[netem_delay_seconds(entry) for entry in netem]
   if len(netem)!=1 or not any(delay is not None and abs(delay-0.05)<0.001 for delay in delays):
    raise RuntimeError(f'WAN qdisc on {ip} does not record the required 50 ms one-way delay: {qdisc}')
  elif netem:
   raise RuntimeError(f'LAN qdisc on {ip} still contains netem: {qdisc}')
  return {'ip':ip,'peer':peer,'mode':mode,'qdisc':qdisc}
 result=[]
 with ThreadPoolExecutor(max_workers=12) as pool:
  for f in as_completed([pool.submit(host,ip) for ip in ips]):
   item=f.result();result.append(item);print(f"Network {mode}: {len(result)}/{len(ips)} {item['ip']} OK",flush=True)
 # All qdiscs are now installed/removed. Measure after the barrier so a WAN
 # ping cannot observe only one 50 ms egress leg during concurrent setup.
 for item in result:
  ping = subprocess.run(
   ['ssh','-i',str(ssh_key()),'-o','BatchMode=yes','-o','ConnectTimeout=10',
    '-o','StrictHostKeyChecking=accept-new',f"root@{ssh_address(item['ip'])}",
    'ping -n -c 7 -W 2 '+shlex.quote(item['peer'])],
   capture_output=True,text=True,timeout=25,
  )
  if ping.returncode:
   raise RuntimeError(f"RTT measurement failed on {item['ip']}: {ping.stderr}")
  try:
   samples=ping_samples(ping.stdout)
  except ValueError:
   raise RuntimeError(f"Could not parse RTT on {item['ip']}: {ping.stdout}")
  item['rtt_samples_ms']=samples
  item['rtt_median_ms']=statistics.median(samples)
  expected = (95,105,'100 ± 5') if mode=='wan' else (0,1,'below 1')
  if not expected[0] < item['rtt_median_ms'] <= expected[1]:
   raise RuntimeError(
    f"{mode.upper()} median RTT on {item['ip']} is {item['rtt_median_ms']} ms; "
    f"expected {expected[2]} ms from paper §7.1"
   )
 if os.environ.get('AE_RUN_DIR'):
  with (Path(os.environ['AE_RUN_DIR'])/'network.jsonl').open('a') as stream:
   stream.write(json.dumps({'timestamp':datetime.now(timezone.utc).isoformat(),'hosts':result})+'\n')
 return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['wan','lan']);a=p.parse_args()
 ips=list(dict.fromkeys((REPO/'aliyun/priv_ip.txt').read_text().split()))
 limit=os.environ.get('AE_HOST_LIMIT')
 if limit:ips=ips[:int(limit)]
 if not ips:raise SystemExit('ERROR: empty cluster list')
 configure(a.mode,ips)
