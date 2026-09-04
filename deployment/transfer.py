import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KEY = str(PROJECT_ROOT / "TShard")
COMMON = ["-i", KEY, "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes"]

# Read the IP list
with (PROJECT_ROOT / "aliyun" / "priv_ip.txt").open("r") as file:
    ips = [ln.strip() for ln in file.readlines() if ln.strip()]


def scp_command(ip: str) -> None:
    source_dir = PROJECT_ROOT / "deployment" / "sourcefile"
    source_file = str(source_dir / "archive.tar.gz")
    source_file1 = str(source_dir / "init.sh")
    source_file3 = str(source_dir / "damysus_updated.tar.gz")
    destination = f"root@{ip}:/root/"

    # Remove old init scripts on the node so fresh copies are not confused with stale content.
    subprocess.run(
        ["ssh"]
        + COMMON
        + [
            f"root@{ip}",
            "rm -f /root/init.sh /root/archive.tar.gz /root/damysus_updated.tar.gz",
        ],
        check=False,
    )

    command = ["scp"] + COMMON + [source_file, destination]
    command1 = ["scp"] + COMMON + [source_file1, destination]
    command3 = ["scp"] + COMMON + [source_file3, destination]
    try:
        subprocess.run(command, check=True)
        subprocess.run(command1, check=True)
        subprocess.run(command3, check=True)
        print(f"Successfully transferred files to {ip}")
    except subprocess.CalledProcessError as e:
        print(f"Failed to transfer file to {ip}: {e}")


with ThreadPoolExecutor() as executor:
    executor.map(scp_command, ips)
