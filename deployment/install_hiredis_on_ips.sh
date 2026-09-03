#!/usr/bin/env bash
set -euo pipefail

# Install hiredis on all hosts listed in aliyun/priv_ip.txt and verify.
# Defaults match run.py: SSH user root, key at project root ./TShard.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IP_FILE="${PROJECT_ROOT}/aliyun/priv_ip.txt"
SSH_USER="${SSH_USER:-root}"
SSH_KEY="${SSH_KEY:-${PROJECT_ROOT}/TShard}"
PARALLEL="${PARALLEL:-7}"

if [[ ! -f "${IP_FILE}" ]]; then
  echo "ERROR: IP list not found: ${IP_FILE}" >&2
  exit 1
fi

if [[ ! -f "${SSH_KEY}" ]]; then
  echo "ERROR: SSH key not found: ${SSH_KEY}" >&2
  exit 1
fi

echo "Using IP list: ${IP_FILE}"
echo "Using SSH user: ${SSH_USER}"
echo "Using SSH key: ${SSH_KEY}"
echo "Parallel jobs: ${PARALLEL}"
echo

run_one() {
  local ip="$1"
  echo "========== [${ip}] START =========="
  ssh -o BatchMode=yes -o StrictHostKeyChecking=no -i "${SSH_KEY}" "${SSH_USER}@${ip}" 'bash -s' <<'REMOTE'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

sudo apt-get update -y
sudo apt-get install -y pkg-config libhiredis-dev

echo "[verify] pkg-config hiredis version:"
pkg-config --modversion hiredis

echo "[verify] pkg-config hiredis flags:"
pkg-config --cflags --libs hiredis

echo "[verify] runtime library cache:"
ldconfig -p | grep -i hiredis || true
REMOTE
  echo "========== [${ip}] OK =========="
}

export -f run_one
export SSH_USER SSH_KEY

failed=0
while IFS= read -r ip; do
  [[ -z "${ip}" ]] && continue
  echo "${ip}"
done < "${IP_FILE}" | xargs -I{} -P "${PARALLEL}" bash -lc 'run_one "$@"' _ {} || failed=1

echo
if [[ "${failed}" -ne 0 ]]; then
  echo "Some hosts failed. Re-run to retry failed nodes."
  exit 1
fi

echo "All hosts completed successfully."
