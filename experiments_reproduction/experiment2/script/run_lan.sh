#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
EXP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${EXP_DIR}/log"
RESULT_DIR="${EXP_DIR}/results"
SSH_KEY="${REPO}/TShard"
IP_LIST_FILE="${REPO}/ip_list"
SUMMARY_FILE="${RESULT_DIR}/summary.csv"

# name|totaltee|leader-mode|leader-id
cases=(
    "tee-leader_no-tee-quorum|32|fixed|0"
    "tee-leader_tee-quorum|33|fixed|0"
    "nontee-leader_no-tee-quorum|32|fixed|33"
    "nontee-leader_tee-quorum|33|fixed|33"
)
total_runs=${#cases[@]}

mkdir -p "${LOG_DIR}" "${RESULT_DIR}"

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

# LAN baseline: remove any netem/root qdisc left by a previous WAN experiment.
echo "Removing existing root qdisc on ${#remote_ips[@]} remote host(s)..."
for ip in "${remote_ips[@]}"; do
    ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no "root@${ip}" \
        "sudo tc qdisc del dev eth0 root 2>/dev/null || true"
done

printf 'case,totaltee,leader_mode,leader_id,server_throughput_mean,server_latency_mean,status\n' > "${SUMMARY_FILE}"
: > "${REPO}/stats.txt"

run_one() {
    local case_name="$1"
    local totaltee="$2"
    local leader_mode="$3"
    local leader_id="$4"
    local run_log_dir="${LOG_DIR}/${case_name}"
    local run_result_dir="${RESULT_DIR}/${case_name}"
    local label="${case_name}_m${totaltee}_${leader_mode}_leader${leader_id}"
    local rc summary_line metrics

    mkdir -p "${run_log_dir}/remote" "${run_result_dir}"
    echo "[$(date --iso-8601=seconds)] START ${case_name}"

    (
        cd "${REPO}"
        python3 run.py --p0 \
            --batchsize 400 \
            --payload 256 \
            --faults 32 \
            --totaltee "${totaltee}" \
            --leader-mode "${leader_mode}" \
            --leader-id "${leader_id}" \
            --stats-summary-label "${label}"
    ) > >(tee "${run_log_dir}/orchestrator.log") 2>&1
    rc=${PIPESTATUS[0]}

    if [[ -d "${REPO}/out" ]]; then
        cp -a "${REPO}/out/." "${run_log_dir}/remote/"
    fi
    if [[ -d "${REPO}/stats" ]]; then
        cp -a "${REPO}/stats/." "${run_result_dir}/"
    fi

    summary_line="$(tail -n 1 "${REPO}/stats.txt" 2>/dev/null || true)"
    if [[ ${rc} -eq 0 && "${summary_line}" == "${label}, "* ]]; then
        metrics="${summary_line#"${label}, "}"
        printf '%s,%s,%s,%s,%s,success\n' \
            "${case_name}" "${totaltee}" "${leader_mode}" "${leader_id}" "${metrics}" \
            >> "${SUMMARY_FILE}"
    else
        printf '%s,%s,%s,%s,,,failed(%d)\n' \
            "${case_name}" "${totaltee}" "${leader_mode}" "${leader_id}" "${rc}" \
            >> "${SUMMARY_FILE}"
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

cp "${REPO}/stats.txt" "${RESULT_DIR}/run.py-summary-raw.txt"
echo "Experiment 2 complete: $((total_runs - failed))/${total_runs} succeeded; summary=${SUMMARY_FILE}"
(( failed == 0 ))
