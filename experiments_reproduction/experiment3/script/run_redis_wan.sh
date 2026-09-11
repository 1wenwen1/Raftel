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
PER_RUN_FILE="$(mktemp)"

protocol_flags=(p0 p1 p2 p3 p4)
protocol_names=(Raftel Chained Achilles Hotstuff Basic-Damysus)
repeats=3
faults=8
requested_totaltee=9
# P0-5: load sweep — run at multiple client counts to produce a throughput-latency curve.
# Paper Figure 6 shows a curve, not a single point.
load_sweep_clients=(1 2 4 8 16 32)
# AE FIX (§7.6): paper specifies "1 KB values" (kv-value-len=1024).
# KVAppCodec::encode requires klen + vlen + 14 ≤ PAYLOAD_SIZE.
# keyspace=10000 → key max 5 chars; 5+1024+14=1043, so PAYLOAD_SIZE must be ≥1043.
# Original script used payload=256 which caused encode() to return false silently.
# Correct values: payload=1100 (PAYLOAD_SIZE), kv-value-len=1024.
payload_size=1100
kv_value_length=1024
views=30

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
: > "${STATS_FILE}"

remove_wan_delay() {
    local ip
    for ip in "${remote_ips[@]}"; do
        ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no "root@${ip}" \
            "sudo tc qdisc del dev eth0 root 2>/dev/null || true" || true
    done
}
cleanup() {
    remove_wan_delay
    rm -f "${PER_RUN_FILE}"
}
trap cleanup EXIT INT TERM

echo "Configuring 50ms WAN delay on ${#remote_ips[@]} remote host(s)..."
for ip in "${remote_ips[@]}"; do
    # P0-4: WAN netem setup failures must be fatal — a silent skip means some
    # node pairs have no delay, making the result invalid.
    ssh -i "${SSH_KEY}" -o StrictHostKeyChecking=no "root@${ip}" \
        "sudo tc qdisc del dev eth0 root 2>/dev/null || true; sudo tc qdisc add dev eth0 root netem delay 50ms" \
        || { echo "ERROR: failed to configure netem on ${ip}" >&2; exit 1; }
done

printf 'protocol,load_clients,repeat,e2e_throughput_ktps,e2e_latency_avg_ms,e2e_latency_p50_ms,e2e_latency_p95_ms,e2e_latency_p99_ms,num_completed,status\n' > "${PER_RUN_FILE}"

# AE (§三): run a fixed 5-view warm-up before each measurement point and discard
# the result.  The warm-up is intentionally not configurable so that the paper
# parameters remain the only thing that controls the measurement.
warmup_one() {
    local flag="$1"
    local protocol="$2"
    local num_clients="$3"

    echo "[$(date --iso-8601=seconds)] WARMUP ${protocol}_cl${num_clients} (5 views, result discarded)"
    (
        cd "${REPO}"
        python3 run.py "--${flag}" \
            --sgx-mode HW \
            --experiment-number 3 \
            --batchsize 400 \
            --payload "${payload_size}" \
            --faults "${faults}" \
            --totaltee "${requested_totaltee}" \
            --views 5 \
            --cl-num "${num_clients}" \
            --cl-trans 200 \
            --cl-sleep 0 \
            --leader-mode fixed \
            --leader-id 0 \
            --redis \
            --kv-set-ratio 100 \
            --kv-get-ratio 0 \
            --kv-del-ratio 0 \
            --kv-keyspace 10000 \
            --kv-value-len "${kv_value_length}"
    ) >/dev/null 2>&1 || true   # warm-up failures are non-fatal
}

run_one() {
    local flag="$1"
    local protocol="$2"
    local num_clients="$3"
    local repeat="$4"
    local tag="${protocol}_cl${num_clients}_repeat${repeat}"
    local run_log_dir="${LOG_DIR}/${tag}"
    local run_result_dir="${RESULT_DIR}/raw/${tag}"
    local rc metrics

    mkdir -p "${run_log_dir}/remote" "${run_result_dir}"

    # AE (§三): 5-view warm-up before the measured run
    warmup_one "${flag}" "${protocol}" "${num_clients}"

    echo "[$(date --iso-8601=seconds)] START ${tag} (clients=${num_clients})"

    (
        cd "${REPO}"
        # P0-2: pass --sgx-mode HW for cloud paper runs
        # AE FIX (§7.6): payload=1100, kv-value-len=1024 — see variable definitions above
        python3 run.py "--${flag}" \
            --sgx-mode HW \
            --experiment-number 3 \
            --batchsize 400 \
            --payload "${payload_size}" \
            --faults "${faults}" \
            --totaltee "${requested_totaltee}" \
            --views "${views}" \
            --cl-num "${num_clients}" \
            --cl-trans 2000 \
            --cl-sleep 0 \
            --leader-mode fixed \
            --leader-id 0 \
            --redis \
            --kv-set-ratio 100 \
            --kv-get-ratio 0 \
            --kv-del-ratio 0 \
            --kv-keyspace 10000 \
            --kv-value-len "${kv_value_length}"
    ) > >(tee "${run_log_dir}/orchestrator.log") 2>&1
    rc=${PIPESTATUS[0]}

    if [[ -d "${CURRENT_LOG_DIR}" ]]; then
        cp -a "${CURRENT_LOG_DIR}/." "${run_log_dir}/remote/"
    fi
    if [[ -d "${CURRENT_RESULT_DIR}" ]]; then
        cp -a "${CURRENT_RESULT_DIR}/." "${run_result_dir}/"
    fi

    if [[ ${rc} -eq 0 ]]; then
        if metrics="$(python3 "${SCRIPT_DIR}/summarize_e2e.py" run "${run_result_dir}")"; then
            # P0-7: check num_completed > 0 to guard against silent all-failure runs
            num_completed="$(echo "${metrics}" | cut -d',' -f6)"
            if [[ "${num_completed}" == "0" || "${num_completed}" == "0.0" ]]; then
                rc=1
                printf '%s,%s,%s,,,,,,,failed(zero-completions)\n' "${protocol}" "${num_clients}" "${repeat}" >> "${PER_RUN_FILE}"
            else
                printf '%s,%s,%s,%s,success\n' "${protocol}" "${num_clients}" "${repeat}" "${metrics}" >> "${PER_RUN_FILE}"
            fi
        else
            rc=1
            printf '%s,%s,%s,,,,,,,failed(no-e2e-data)\n' "${protocol}" "${num_clients}" "${repeat}" >> "${PER_RUN_FILE}"
        fi
    else
        printf '%s,%s,%s,,,,,,,failed(run-exit-%d)\n' "${protocol}" "${num_clients}" "${repeat}" "${rc}" >> "${PER_RUN_FILE}"
    fi

    echo "[$(date --iso-8601=seconds)] END ${tag}, exit=${rc}"
    return "${rc}"
}

failed=0
# P0-5: sweep over load points to produce throughput-latency curve (paper Figure 6)
for i in "${!protocol_flags[@]}"; do
    for num_clients in "${load_sweep_clients[@]}"; do
        for ((repeat = 1; repeat <= repeats; repeat++)); do
            if ! run_one "${protocol_flags[$i]}" "${protocol_names[$i]}" "${num_clients}" "${repeat}"; then
                failed=$((failed + 1))
            fi
            sleep 5
        done
    done
done

python3 "${SCRIPT_DIR}/summarize_e2e.py" aggregate "${PER_RUN_FILE}" "${STATS_FILE}"
total_runs=$(( ${#protocol_flags[@]} * ${#load_sweep_clients[@]} * repeats ))
echo "Experiment 3 complete: $((total_runs - failed))/${total_runs} succeeded; statistics=${STATS_FILE}"
(( failed == 0 ))
