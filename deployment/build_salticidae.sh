#!/usr/bin/env bash
# Build the vendored Salticidae inside the pinned container, into the checkout.
#
# Salticidae generates `salticidae/include/salticidae/config.h` with CMake's
# configure_file, which resolves a relative output path against the *binary*
# directory while `include_directories(include)` resolves against the *source*
# directory.  Only an in-source build puts the header where the compiler looks
# for it.  An out-of-source `cmake -S . -B build` fails with
# "salticidae/config.h: No such file or directory".
#
# The build has to run inside the container rather than on the host: the
# resulting static library is linked into the SGX binaries, and those are built
# with the container's Ubuntu 20.04 toolchain.  Building it with a newer host
# compiler and linking it into an older toolchain is not something anyone should
# have to debug at evaluation time.
#
# Safe to re-run; it is a no-op once the header and library exist.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${RAFTEL_IMAGE:-raftel-ae}"
DOCKER="${RAFTEL_DOCKER:-docker}"

if [[ -f "${REPO}/salticidae/include/salticidae/config.h" && \
      -f "${REPO}/salticidae/lib/libsalticidae.a" ]]; then
    echo "salticidae already built in ${REPO}/salticidae"
    exit 0
fi

echo "Building salticidae inside ${IMAGE} (one-time, ~1 minute)..."
# The checkout is mounted read-write because the build writes back into it.
# Container, not host, toolchain -- see the note above.
$DOCKER run --rm \
    -v "${REPO}:${REPO}" \
    -w "${REPO}/salticidae" \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp \
    "${IMAGE}" \
    bash -c 'set -e; cmake . -DCMAKE_INSTALL_PREFIX=. >/dev/null; make -j"$(nproc)" >/dev/null; make install >/dev/null'

test -f "${REPO}/salticidae/include/salticidae/config.h"
test -f "${REPO}/salticidae/lib/libsalticidae.a"
echo "salticidae ready:"
ls -l "${REPO}/salticidae/include/salticidae/config.h" "${REPO}/salticidae/lib/libsalticidae.a"
