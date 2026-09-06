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

protocol_flags=(p0 p1 p2 p3 p4 p0)
protocol_names=(Raftel Chained Achilles Hotstuff Basic-Damysus Raftel-Worst)
fault_values=(1 2 4 8 16 32)
total_runs=$(( ${#protocol_flags[@]} * ${#fault_values[@]} ))

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

remove_wan_delay() {
    local ip
    for ip in "${remote_ips[@]}"; do
        ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no "root@${ip}" \
            "sudo tc qdisc del dev eth0 root 2>/dev/null || true" || true
    done
}

trap remove_wan_delay EXIT INT TERM

echo "Configuring 50ms WAN delay on ${#remote_ips[@]} remote host(s)..."
for ip in "${remote_ips[@]}"; do
    ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no "root@${ip}" \
        "sudo tc qdisc del dev eth0 root 2>/dev/null || true; sudo tc qdisc add dev eth0 root netem delay 50ms"
done

: > "${STATS_FILE}"

run_one() {
    local flag="$1"
    local protocol="$2"
    local faults="$3"
    local tag="${protocol}_f${faults}"
    local run_log_dir="${LOG_DIR}/${tag}"
    local run_result_dir="${RESULT_DIR}/${tag}"
    local rc summary_line
    local -a protocol_args=()

    if [[ "${protocol}" == "Raftel-Worst" ]]; then
        protocol_args=(
            --totaltee "${faults}"
            --leader-mode fixed
            --leader-id "$((faults + 1))"
        )
    elif [[ "${flag}" == "p0" ]]; then
        protocol_args=(--totaltee "$((faults + 1))")
    fi

    mkdir -p "${run_log_dir}/remote" "${run_result_dir}"
    echo "[$(date --iso-8601=seconds)] START ${tag}"

    (
        cd "${REPO}"
        python3 run.py "--${flag}" \
            --experiment-number 1 \
            --batchsize 400 \
            --payload 256 \
            --faults "${faults}" \
            --repeats 1 \
            "${protocol_args[@]}" \
            --stats-summary-label "${tag}"
    ) > >(tee "${run_log_dir}/orchestrator.log") 2>&1
    rc=${PIPESTATUS[0]}

    # Archive logs and raw node results before the next run replaces current/.
    if [[ -d "${CURRENT_LOG_DIR}" ]]; then
        cp -a "${CURRENT_LOG_DIR}/." "${run_log_dir}/remote/"
    fi
    if [[ -d "${CURRENT_RESULT_DIR}" ]]; then
        cp -a "${CURRENT_RESULT_DIR}/." "${run_result_dir}/"
    fi

    summary_line="$(tail -n 1 "${STATS_FILE}" 2>/dev/null || true)"
    if [[ ${rc} -ne 0 || "${summary_line}" != "${tag}, "* ]]; then
        rc=1
    fi

    echo "[$(date --iso-8601=seconds)] END ${tag}, exit=${rc}"
    return "${rc}"
}

failed=0
for i in "${!protocol_flags[@]}"; do
    for faults in "${fault_values[@]}"; do
        if ! run_one "${protocol_flags[$i]}" "${protocol_names[$i]}" "${faults}"; then
            failed=$((failed + 1))
        fi
        sleep 5
    done
done

echo "Experiment 1 complete: $((total_runs - failed))/${total_runs} succeeded; statistics=${STATS_FILE}"
(( failed == 0 ))
