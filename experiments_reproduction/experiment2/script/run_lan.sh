#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
EXP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
EXE_DIR="${EXP_DIR}/exe"
LOG_DIR="${EXP_DIR}/log"
OUT_DIR="${EXP_DIR}/out"
RESULT_DIR="${EXP_DIR}/results"
CURRENT_LOG_DIR="${LOG_DIR}/current"
CURRENT_RESULT_DIR="${RESULT_DIR}/current"
SSH_KEY="${REPO}/TShard"
IP_LIST_FILE="${REPO}/ip_list"
STATS_FILE="${EXP_DIR}/stats.txt"

# name|totaltee|leader-mode|leader-id
cases=(
    "tee-leader_no-tee-quorum|32|fixed|0"
    "tee-leader_tee-quorum|33|fixed|0"
    "nontee-leader_no-tee-quorum|32|fixed|33"
    "nontee-leader_tee-quorum|33|fixed|33"
)
total_runs=${#cases[@]}

if [[ ! -f "${SSH_KEY}" ]]; then
    echo "SSH key not found: ${SSH_KEY}" >&2
    exit 1
fi
if [[ ! -f "${IP_LIST_FILE}" ]]; then
    echo "IP list not found: ${IP_LIST_FILE}" >&2
    exit 1
fi

mapfile -t remote_ips < <(awk 'NF && !seen[$1]++ {print $1}' "${IP_LIST_FILE}")
if (( ${#remote_ips[@]} == 0 )); then
    echo "No remote server IPs found in ${IP_LIST_FILE}" >&2
    exit 1
fi

clear_experiment_dir() {
    local dir="$1"
    local entry
    mkdir -p "${dir}"
    shopt -s dotglob nullglob
    for entry in "${dir}"/*; do
        [[ "${entry##*/}" == ".gitkeep" ]] && continue
        rm -rf -- "${entry}"
    done
    shopt -u dotglob nullglob
}

for dir in "${EXE_DIR}" "${LOG_DIR}" "${OUT_DIR}" "${RESULT_DIR}"; do
    clear_experiment_dir "${dir}"
done

# LAN baseline: remove any netem/root qdisc left by a previous WAN experiment.
echo "Removing existing root qdisc on ${#remote_ips[@]} remote host(s)..."
for ip in "${remote_ips[@]}"; do
    ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no "root@${ip}" \
        "sudo tc qdisc del dev eth0 root 2>/dev/null || true"
done

: > "${STATS_FILE}"

run_one() {
    local case_name="$1"
    local totaltee="$2"
    local leader_mode="$3"
    local leader_id="$4"
    local run_log_dir="${LOG_DIR}/${case_name}"
    local run_result_dir="${RESULT_DIR}/${case_name}"
    local label="${case_name}_m${totaltee}_${leader_mode}_leader${leader_id}"
    local rc summary_line

    mkdir -p "${run_log_dir}/remote" "${run_result_dir}"
    echo "[$(date --iso-8601=seconds)] START ${case_name}"

    (
        cd "${REPO}"
        python3 run.py --p0 \
            --experiment-number 2 \
            --batchsize 400 \
            --payload 256 \
            --faults 32 \
            --totaltee "${totaltee}" \
            --leader-mode "${leader_mode}" \
            --leader-id "${leader_id}" \
            --stats-summary-label "${label}"
    ) > >(tee "${run_log_dir}/orchestrator.log") 2>&1
    rc=${PIPESTATUS[0]}

    if [[ -d "${CURRENT_LOG_DIR}" ]]; then
        cp -a "${CURRENT_LOG_DIR}/." "${run_log_dir}/remote/"
    fi
    if [[ -d "${CURRENT_RESULT_DIR}" ]]; then
        cp -a "${CURRENT_RESULT_DIR}/." "${run_result_dir}/"
    fi

    summary_line="$(tail -n 1 "${STATS_FILE}" 2>/dev/null || true)"
    if [[ ${rc} -ne 0 || "${summary_line}" != "${label}, "* ]]; then
        rc=1
    fi

    echo "[$(date --iso-8601=seconds)] END ${case_name}, exit=${rc}"
    return "${rc}"
}

failed=0
for case_spec in "${cases[@]}"; do
    IFS='|' read -r case_name totaltee leader_mode leader_id <<< "${case_spec}"
    if ! run_one "${case_name}" "${totaltee}" "${leader_mode}" "${leader_id}"; then
        failed=$((failed + 1))
    fi
    sleep 5
done

echo "Experiment 2 complete: $((total_runs - failed))/${total_runs} succeeded; statistics=${STATS_FILE}"
(( failed == 0 ))
