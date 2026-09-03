#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
EXP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${EXP_DIR}/log"
RESULT_DIR="${EXP_DIR}/results"
SSH_KEY="${REPO}/TShard"
IP_LIST_FILE="${REPO}/ip_list"
PER_RUN_FILE="${RESULT_DIR}/per-run.csv"
SUMMARY_FILE="${RESULT_DIR}/summary.csv"

protocol_flags=(p0 p01 p1 p5 p6)
protocol_names=(HybridTEE Chained-HybridTEE Achilles Hotstuff Basic-Damysus)
repeats=3
faults=8
requested_totaltee=9
clients=4
transactions_per_client=2000
views=30

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

printf 'protocol,repeat,e2e_throughput_ktps,e2e_latency_avg_ms,e2e_latency_p50_ms,e2e_latency_p95_ms,e2e_latency_p99_ms,num_completed,status\n' > "${PER_RUN_FILE}"
: > "${REPO}/stats.txt"

run_one() {
    local flag="$1"
    local protocol="$2"
    local repeat="$3"
    local tag="${protocol}_repeat${repeat}"
    local run_log_dir="${LOG_DIR}/${tag}"
    local run_result_dir="${RESULT_DIR}/raw/${tag}"
    local rc metrics

    mkdir -p "${run_log_dir}/remote" "${run_result_dir}"
    echo "[$(date --iso-8601=seconds)] START ${tag}"

    (
        cd "${REPO}"
        python3 run.py "--${flag}" \
            --batchsize 400 \
            --payload 256 \
            --faults "${faults}" \
            --totaltee "${requested_totaltee}" \
            --views "${views}" \
            --cl-num "${clients}" \
            --cl-trans "${transactions_per_client}" \
            --cl-sleep 0 \
            --leader-mode fixed \
            --leader-id 0 \
            --redis \
            --kv-set-ratio 100 \
            --kv-get-ratio 0 \
            --kv-del-ratio 0 \
            --kv-keyspace 10000 \
            --kv-value-len 1024
    ) > >(tee "${run_log_dir}/orchestrator.log") 2>&1
    rc=${PIPESTATUS[0]}

    if [[ -d "${REPO}/out" ]]; then
        cp -a "${REPO}/out/." "${run_log_dir}/remote/"
    fi
    if [[ -d "${REPO}/stats" ]]; then
        cp -a "${REPO}/stats/." "${run_result_dir}/"
    fi

    if [[ ${rc} -eq 0 ]]; then
        if metrics="$(python3 "${SCRIPT_DIR}/summarize_e2e.py" run "${run_result_dir}")"; then
            printf '%s,%s,%s,success\n' "${protocol}" "${repeat}" "${metrics}" >> "${PER_RUN_FILE}"
        else
            rc=1
            printf '%s,%s,,,,,,,failed(no-e2e-data)\n' "${protocol}" "${repeat}" >> "${PER_RUN_FILE}"
        fi
    else
        printf '%s,%s,,,,,,,failed(run-exit-%d)\n' "${protocol}" "${repeat}" "${rc}" >> "${PER_RUN_FILE}"
    fi

    echo "[$(date --iso-8601=seconds)] END ${tag}, exit=${rc}"
    return "${rc}"
}

failed=0
for i in "${!protocol_flags[@]}"; do
    for ((repeat = 1; repeat <= repeats; repeat++)); do
        if ! run_one "${protocol_flags[$i]}" "${protocol_names[$i]}" "${repeat}"; then
            failed=$((failed + 1))
        fi
        sleep 5
    done
done

python3 "${SCRIPT_DIR}/summarize_e2e.py" aggregate "${PER_RUN_FILE}" "${SUMMARY_FILE}"
total_runs=$(( ${#protocol_flags[@]} * repeats ))
echo "Experiment 3 complete: $((total_runs - failed))/${total_runs} succeeded; summary=${SUMMARY_FILE}"
(( failed == 0 ))
