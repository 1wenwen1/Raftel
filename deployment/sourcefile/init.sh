#!/bin/bash
set -e

apt update

tar -xvzf archive.tar.gz

if [ ! -e /dev/sgx_enclave ] || [ ! -e /dev/sgx_provision ]; then
    echo "ERROR: Intel SGX devices are unavailable after the SGX initialization and reboot." >&2
    echo "Expected /dev/sgx_enclave and /dev/sgx_provision." >&2
    exit 1
fi

echo "Intel SGX in-kernel driver is available."
ls -l /dev/sgx_enclave /dev/sgx_provision

DEBIAN_FRONTEND=noninteractive apt-get install -y build-essential ocaml ocamlbuild automake autoconf libtool wget python-is-python3 libssl-dev git cmake perl
apt-get install -y build-essential python-is-python3
apt-get install -y libssl-dev libcurl4-openssl-dev protobuf-compiler libprotobuf-dev debhelper cmake reprepro unzip pkgconf libboost-dev libboost-system-dev libboost-thread-dev lsb-release libsystemd0
apt-get install -y libssl-dev libcurl4-openssl-dev libprotobuf-dev

# sdk
if [ ! -f /opt/intel/sgxsdk/environment ]; then
    echo -e "no\n/opt/intel\n" | ./sgx_linux_x64_sdk_2.23.100.2.bin
else
    echo "Intel SGX SDK is already installed."
fi

# psw
tar -xvzf sgx_debian_local_repo.tar.gz
echo 'deb [trusted=yes arch=amd64] file:/root/sgx_debian_local_repo focal main' > /etc/apt/sources.list.d/intel-sgx-local.list
apt-get -o Acquire::GzipIndexes=false -o APT::Sandbox::User=root update
apt-get install -y libsgx-launch libsgx-urts libsgx-epid libsgx-quote-ex libsgx-dcap-ql
ldconfig

if ! dpkg-query -W -f='${Status}\n' libsgx-urts 2>/dev/null | grep -q 'install ok installed'; then
    echo "ERROR: Intel SGX PSW package libsgx-urts is not installed." >&2
    exit 1
fi

if ! ldconfig -p | grep -q 'libsgx_urts\.so'; then
    echo "ERROR: libsgx_urts.so is not visible to the dynamic linker." >&2
    exit 1
fi

echo "Intel SGX PSW runtime (libsgx-urts) is available."

tar -xvzf sgxssl.tar.gz
mkdir -p /opt/intel/sgxssl//lib64/
mkdir -p /opt/intel/sgxssl//include/
cp -prf package/lib64//*  /opt/intel/sgxssl//lib64/
cp -prf package/include//* /opt/intel/sgxssl//include/

grep -qxF 'export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/intel/sgxsdk/sdk_libs' ~/.bashrc || \
    echo 'export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/intel/sgxsdk/sdk_libs' >> ~/.bashrc
grep -qxF 'export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/lib' ~/.bashrc || \
    echo 'export LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/usr/local/lib' >> ~/.bashrc
source ~/.bashrc


sudo apt install -y cmake libuv1-dev libssl-dev
python3 -m pip install pathlib matplotlib
source /opt/intel/sgxsdk/environment

cd ~
mkdir -p resilientdb && cd resilientdb
mkdir -p obj
mkdir -p results

cd ~
if [ -d /root/Raftel/.git ]; then
    git -C /root/Raftel pull --ff-only origin main
else
    git clone https://github.com/1wenwen1/Raftel.git /root/Raftel
fi
cd Raftel
git submodule init
git submodule update
(cd salticidae; cmake . -DCMAKE_INSTALL_PREFIX=.; make; make install)


# KV store backend for experiments (run.py starts redis-server per replica on 127.0.0.1)
DEBIAN_FRONTEND=noninteractive apt-get install -y redis-server
