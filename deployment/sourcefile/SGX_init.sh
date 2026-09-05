#!/bin/bash
set -euo pipefail

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y cpuid

if ! cpuid -1 -l 0x7 | grep -qi 'SGX:.*true'; then
    echo "ERROR: this instance does not expose Intel SGX through CPUID." >&2
    echo "Use an Alibaba Cloud vSGX instance (for example g7t) with an SGX-capable UEFI image." >&2
    exit 1
fi

if [ ! -e /dev/sgx_enclave ] || [ ! -e /dev/sgx_provision ]; then
    modprobe sgx 2>/dev/null || true
fi

if [ -e /dev/sgx_enclave ] && [ -e /dev/sgx_provision ]; then
    echo "Intel SGX in-kernel driver is already available."
    ls -l /dev/sgx_enclave /dev/sgx_provision
    exit 0
fi

running_kernel=$(uname -r | cut -d- -f1)
if dpkg --compare-versions "$running_kernel" lt 5.11; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y linux-generic-hwe-20.04
    echo "A Linux kernel with the in-kernel SGX driver has been installed."
    echo "The coordinator will reboot this server."
    exit 0
fi

echo "ERROR: SGX is exposed by CPUID, but /dev/sgx_enclave and /dev/sgx_provision are unavailable." >&2
echo "Check that CONFIG_X86_SGX is enabled, or recreate the instance with an Alibaba Cloud SGX image." >&2
exit 1
