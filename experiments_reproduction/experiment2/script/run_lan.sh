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

sets=(set1 set2 set3 set4)
fault_values=(1 2 4 8 16 32)
total_runs=$(( ${#sets[@]} * ${#fault_values[@]} ))

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
    local set_name="$1"
    local faults="$2"
    local totaltee leader_id
    local label="${set_name}_f${faults}"
    local run_log_dir="${LOG_DIR}/${label}"
    local run_result_dir="${RESULT_DIR}/${label}"
    local rc summary_line

    case "${set_name}" in
        set1) totaltee=$((faults + 1)); leader_id=0 ;;
        set2) totaltee=${faults};       leader_id=0 ;;
        set3) totaltee=$((faults + 1)); leader_id=$((faults + 1)) ;;
        set4) totaltee=${faults};       leader_id=$((faults + 1)) ;;
        *)
            echo "Unknown experiment set: ${set_name}" >&2
            return 1
            ;;
    esac

    mkdir -p "${run_log_dir}/remote" "${run_result_dir}"
    echo "[$(date --iso-8601=seconds)] START ${label}: totaltee=${totaltee}, leader=${leader_id}"

    (
        cd "${REPO}"
        python3 run.py --p0 \
            --experiment-number 2 \
            --batchsize 400 \
            --payload 256 \
            --faults "${faults}" \
            --totaltee "${totaltee}" \
            --leader-mode fixed \
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

    echo "[$(date --iso-8601=seconds)] END ${label}, exit=${rc}"
    return "${rc}"
}

failed=0
for set_name in "${sets[@]}"; do
    for faults in "${fault_values[@]}"; do
        if ! run_one "${set_name}" "${faults}"; then
            failed=$((failed + 1))
        fi
        sleep 5
    done
done

echo "Experiment 2 complete: $((total_runs - failed))/${total_runs} succeeded; statistics=${STATS_FILE}"
(( failed == 0 ))
