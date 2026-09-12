import subprocess
import tarfile
import tempfile
import json
import hashlib
import io
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT / "aliyun"))
from cloud_common import load_config, ssh_key

CONFIG = load_config()
KEY = str(ssh_key(CONFIG))
COMMON = ["-i", KEY, "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes"]

# AE FIX: ship the current evaluated files, including dirty changes; never keys/config.
archive_temp = tempfile.NamedTemporaryFile(suffix=".tar.gz")
with tarfile.open(archive_temp.name, "w:gz") as archive:
    deployed_manifest = PROJECT_ROOT / ".ae-source.json"
    if (PROJECT_ROOT / ".git").exists():
        listed = subprocess.check_output(
            ["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=PROJECT_ROOT
        ).decode().split("\0")
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
        ).strip()
        dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=PROJECT_ROOT,
            text=True,
        ).strip())
        source_diff = subprocess.check_output(
            ["git", "diff", "HEAD", "--binary", "--", ".", ":(exclude)TShard"],
            cwd=PROJECT_ROOT,
        )
    elif deployed_manifest.is_file():
        prior = json.loads(deployed_manifest.read_text())
        listed = list(prior.get("sha256", {}))
        commit = prior.get("git_commit", "unknown")
        dirty = bool(prior.get("working_tree_dirty", False))
        deployed_diff = PROJECT_ROOT / ".ae-source.diff"
        source_diff = deployed_diff.read_bytes() if deployed_diff.is_file() else b""
    else:
        raise RuntimeError("Source provenance is unavailable: expected .git or .ae-source.json")
    shipped_files = {}
    for name in listed:
        source = PROJECT_ROOT / name
        private_or_runtime = (
            name == "TShard"
            or name == "aliyun/config.json"
            or name.startswith("runs/") and not name.startswith("runs/reference/")
            or name.startswith("aliyun/") and Path(name).suffix in {".pem", ".key"}
            or name in {
                "aliyun/hosts.json", "aliyun/runner.json", "aliyun/priv_ip.txt",
                "aliyun/public_ip.txt", "aliyun/instances.txt", "aliyun/cluster_plan.json",
            }
        )
        if name and source.is_file() and not private_or_runtime:
            archive.add(source, arcname="Raftel/" + name, recursive=False)
            shipped_files[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    salt = PROJECT_ROOT / "salticidae"
    if not (salt / "CMakeLists.txt").exists():
        raise RuntimeError("Initialize salticidae before deployment: git submodule update --init --recursive")
    archive.add(salt, arcname="Raftel/salticidae", filter=lambda info: None if "/.git" in info.name else info)

    # The deployed coordinator deliberately has no .git directory. Preserve
    # enough source identity for every run to remain auditable there.
    metadata = json.dumps(
        {
            "git_commit": commit,
            "working_tree_dirty": dirty,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sha256": dict(sorted(shipped_files.items())),
        },
        indent=2,
    ).encode() + b"\n"
    info = tarfile.TarInfo("Raftel/.ae-source.json")
    info.size = len(metadata)
    info.mode = 0o644
    archive.addfile(info, io.BytesIO(metadata))

    info = tarfile.TarInfo("Raftel/.ae-source.diff")
    info.size = len(source_diff)
    info.mode = 0o644
    archive.addfile(info, io.BytesIO(source_diff))

runner = json.loads((PROJECT_ROOT / "aliyun" / "runner.json").read_text())
# The long-lived runner is tracked separately from the disposable replica
# inventory. Always deploy the reviewer snapshot to it, including when no
# replica cluster currently exists.
with (PROJECT_ROOT / "aliyun" / "public_ip.txt").open("r") as file:
    replica_ips = [ln.strip() for ln in file.readlines() if ln.strip()]
ips = list(dict.fromkeys([runner.get("public_ip"), *replica_ips]))
ips = [ip for ip in ips if ip]

# A developer checkout may intentionally track only the runner. In that case,
# the prepared runner's live replica inventory is authoritative and must not be
# replaced with empty files during a source-only update.
local_private_inventory = PROJECT_ROOT / "aliyun" / "priv_ip.txt"
copy_replica_inventory = bool(
    local_private_inventory.is_file()
    and local_private_inventory.read_text().strip()
)


def scp_command(ip: str) -> None:
    source_dir = PROJECT_ROOT / "deployment" / "sourcefile"
    source_file = str(source_dir / "archive.tar.gz")
    source_file1 = str(source_dir / "init.sh")
    source_file2 = str(source_dir / "SGX_init.sh")
    destination = f"root@{ip}:/root/"

    # Remove stale deployment inputs and the obsolete remote address generator.
    subprocess.run(
        ["ssh"]
        + COMMON
        + [
            f"root@{ip}",
            "rm -f /root/init.sh /root/SGX_init.sh /root/archive.tar.gz "
            "/root/Raftel/deployment/gen_ip.py",
        ],
        check=False,
    )

    command = ["scp"] + COMMON + [source_file, destination]
    command1 = ["scp"] + COMMON + [source_file1, destination]
    command2 = ["scp"] + COMMON + [source_file2, destination]
    try:
        subprocess.run(command, check=True)
        subprocess.run(command1, check=True)
        subprocess.run(command2, check=True)
        subprocess.run(["scp"] + COMMON + [archive_temp.name, f"root@{ip}:/root/ae-source.tar.gz"], check=True)
        subprocess.run(["ssh"] + COMMON + [f"root@{ip}", "tar -xzf /root/ae-source.tar.gz -C /root"], check=True)
        inventory_files = [str(PROJECT_ROOT / "aliyun" / "runner.json")]
        if copy_replica_inventory:
            inventory_files.extend([
                str(PROJECT_ROOT / "aliyun" / "hosts.json"),
                str(PROJECT_ROOT / "aliyun" / "priv_ip.txt"),
            ])
        subprocess.run(
            ["scp"] + COMMON + inventory_files + [f"root@{ip}:/root/Raftel/aliyun/"],
            check=True,
        )
        if ip == runner.get("public_ip"):
            subprocess.run(
                ["scp"] + COMMON + [
                    KEY,
                    str(PROJECT_ROOT / "aliyun" / "config.json"),
                    f"root@{ip}:/root/Raftel/aliyun/",
                ],
                check=True,
            )
            subprocess.run(
                ["scp"] + COMMON + [KEY, f"root@{ip}:/root/Raftel/TShard"],
                check=True,
            )
            subprocess.run(
                ["ssh"] + COMMON + [
                    f"root@{ip}",
                    "chmod 600 /root/Raftel/TShard /root/Raftel/aliyun/raftel-ae.pem /root/Raftel/aliyun/config.json",
                ],
                check=True,
            )
        print(f"Successfully transferred files to {ip}")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to transfer files to {ip}") from e


with ThreadPoolExecutor() as executor:
    list(executor.map(scp_command, ips))
