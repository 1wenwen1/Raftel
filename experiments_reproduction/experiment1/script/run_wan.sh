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

protocol_flags=(p0 p01 p1 p5 p6)
protocol_names=(HybridTEE Chained-HybridTEE Achilles Hotstuff Basic-Damysus)
fault_values=(1 2 4 8 16 32)
total_runs=$(( ${#protocol_flags[@]} * ${#fault_values[@]} ))

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

printf 'protocol,faults,server_throughput_mean,server_latency_mean,status\n' > "${SUMMARY_FILE}"
: > "${REPO}/stats.txt"

run_one() {
    local flag="$1"
    local protocol="$2"
    local faults="$3"
    local tag="${protocol}_f${faults}"
    local run_log_dir="${LOG_DIR}/${tag}"
    local run_result_dir="${RESULT_DIR}/${tag}"
    local rc summary_line

    mkdir -p "${run_log_dir}/remote" "${run_result_dir}"
    echo "[$(date --iso-8601=seconds)] START ${tag}"

    (
        cd "${REPO}"
        python3 run.py "--${flag}" \
            --batchsize 400 \
            --payload 256 \
            --faults "${faults}" \
            --stats-summary-label "${tag}"
    ) > >(tee "${run_log_dir}/orchestrator.log") 2>&1
    rc=${PIPESTATUS[0]}

    # run.py downloads each remote replica's out* file into REPO/out.
    if [[ -d "${REPO}/out" ]]; then
        cp -a "${REPO}/out/." "${run_log_dir}/remote/"
    fi
    # Preserve all raw measurements before the next run replaces local stats.
    if [[ -d "${REPO}/stats" ]]; then
        cp -a "${REPO}/stats/." "${run_result_dir}/"
    fi

    summary_line="$(tail -n 1 "${REPO}/stats.txt" 2>/dev/null || true)"
    if [[ ${rc} -eq 0 && "${summary_line}" == "${tag}, "* ]]; then
        printf '%s,success\n' "${summary_line}" >> "${SUMMARY_FILE}"
    else
        printf '%s,%s,,,failed(%d)\n' "${protocol}" "${faults}" "${rc}" >> "${SUMMARY_FILE}"
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

cp "${REPO}/stats.txt" "${RESULT_DIR}/run.py-summary-raw.txt"
echo "Experiment 1 complete: $((total_runs - failed))/${total_runs} succeeded; summary=${SUMMARY_FILE}"
(( failed == 0 ))
