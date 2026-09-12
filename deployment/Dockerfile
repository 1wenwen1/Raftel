# Build and run the Raftel artifact on any x86-64 host.
#
# The paper's experiments need Ubuntu 20.04, the Intel SGX SDK 2.23.100.2 and
# SGX SSL in fixed locations under /opt/intel.  Reproducing that by hand on a
# different distribution is where most of the setup time goes, so it is pinned
# here as a container instead.
#
# The default build is SGX simulation mode: enclave code compiles and runs
# without SGX hardware, which is enough for the local smoke test and for
# functional checks.  Hardware-mode measurements still need a real SGX machine;
# this image does not turn one into one.
#
#   docker build -f deployment/Dockerfile -t raftel-ae .
#   docker run --rm -it raftel-ae ./ae doctor --profile smoke
#   docker run --rm -it raftel-ae ./ae smoke

FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
ENV LD_LIBRARY_PATH=/opt/intel/sgxsdk/sdk_libs:/opt/intel/sgxssl/lib64:/usr/local/lib

# --- system packages -------------------------------------------------------
# Pinned to the versions the README documents.  libssl-dev on focal is 1.1.1,
# which matters: the SGX SSL package in this repository is built against it.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake git pkg-config ca-certificates \
        libssl-dev libuv1-dev \
        python3 python3-pip \
        libhiredis-dev redis-server \
        tmux iproute2 openssh-client sudo \
        patch file \
    && rm -rf /var/lib/apt/lists/*

# Python 3.8.10 is focal's default, matching the documented environment.
RUN python3 -m pip install --no-cache-dir \
        matplotlib paramiko scp aliyun-python-sdk-core

WORKDIR /root/Raftel

# --- Intel SGX SDK, PSW and SGX SSL ----------------------------------------
# The three installers ship in the repository bundle.  Copying only the archive
# here keeps the layer cache stable when the source tree changes.
COPY deployment/sourcefile/archive.tar.gz /tmp/sgx/
RUN set -eux; \
    cd /tmp/sgx; \
    tar -xzf archive.tar.gz; \
    # SDK, installed to /opt/intel without the interactive prompt.
    printf 'no\n/opt/intel\n' | ./sgx_linux_x64_sdk_2.23.100.2.bin; \
    # PSW runtime, from the bundled local apt repository.
    mkdir -p /root/sgx_debian_local_repo; \
    tar -xzf sgx_debian_local_repo.tar.gz -C /root/; \
    echo 'deb [trusted=yes arch=amd64] file:/root/sgx_debian_local_repo focal main' \
        > /etc/apt/sources.list.d/intel-sgx-local.list; \
    apt-get -o Acquire::GzipIndexes=false update; \
    apt-get install -y --no-install-recommends \
        libsgx-launch libsgx-urts libsgx-epid libsgx-quote-ex libsgx-dcap-ql; \
    ldconfig; \
    # SGX SSL, into the fixed prefix the Makefile expects.
    mkdir -p /opt/intel/sgxssl/lib64 /opt/intel/sgxssl/include; \
    tar -xzf sgxssl.tar.gz; \
    cp -a package/lib64/.   /opt/intel/sgxssl/lib64/; \
    cp -a package/include/. /opt/intel/sgxssl/include/; \
    rm -rf /tmp/sgx; \
    # Fail the build now rather than at experiment time if something is missing.
    ls /opt/intel/sgxsdk/environment >/dev/null; \
    ldconfig -p | grep -q libsgx_urts.so; \
    ls /opt/intel/sgxssl/lib64/libsgx_tsgxssl.a >/dev/null

# --- project ---------------------------------------------------------------
COPY Makefile ./
COPY App ./App
COPY Enclave ./Enclave
COPY salticidae ./salticidae
COPY run.py ae ./
COPY scripts ./scripts
COPY experiments_reproduction ./experiments_reproduction
COPY aliyun ./aliyun
COPY deployment ./deployment

# Salticidae is vendored rather than cloned, so the image does not depend on
# network access at build time.
#
# This must be an IN-SOURCE build.  Its CMakeLists runs
#   configure_file(src/config.h.in include/salticidae/config.h @ONLY)
# and configure_file resolves a relative output against the *binary* directory
# while `include_directories(include)` resolves against the *source* directory.
# Only when both are the same directory does the generated header land where the
# compiler looks for it.  An out-of-source `cmake -S . -B build` fails with
# "salticidae/config.h: No such file or directory".
RUN set -eux; \
    cd salticidae; \
    cmake . -DCMAKE_INSTALL_PREFIX=.; \
    make -j"$(nproc)"; \
    make install; \
    test -f include/salticidae/config.h

# /opt/intel/sgxsdk/environment appends to PKG_CONFIG_PATH without a default,
# so it aborts under `set -u`.  Give the variable a value first.
ENV PKG_CONFIG_PATH=""

# Smoke-test the toolchain at image build time: if the SDK environment or SGX
# SSL is wrong, the reviewer finds out here and not twenty minutes into a run.
RUN set -eux; \
    set +u; . /opt/intel/sgxsdk/environment; set -u; \
    make clean >/dev/null 2>&1 || true; \
    make -j"$(nproc)" SGX_MODE=SIM; \
    ls -l sgxserver sgxclient

CMD ["/bin/bash"]
