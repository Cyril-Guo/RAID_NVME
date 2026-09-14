#!/usr/bin/env bash
# Rewrite Ubuntu APT sources to a domestic mirror (Aliyun) when official hosts are used.
# Also fix ARM Aliyun paths: /ubuntu -> /ubuntu-ports.
# Best-effort; never fails the caller hard (exit 0).
#
# Optional: APT_SOURCES_ROOT=/tmp/fake-apt  (for tests; defaults to /etc/apt)
# Optional: APT_ARCHITECTURE=amd64|arm64|... (for tests)
set -uo pipefail

NODE_IP=${NODE_IP:-unknown}
APT_SOURCES_ROOT=${APT_SOURCES_ROOT:-/etc/apt}

if ! command -v apt-get >/dev/null 2>&1; then
    # Still allow unit tests that only rewrite files without a real apt-get.
    if [ "${APT_SOURCES_ROOT}" = "/etc/apt" ]; then
        exit 0
    fi
fi

architecture=""
if command -v dpkg >/dev/null 2>&1; then
    architecture=$(dpkg --print-architecture 2>/dev/null || true)
fi
architecture=${APT_ARCHITECTURE:-${architecture}}

case "${architecture}" in
    arm64|armhf|armel)
        UBUNTU_PATH="ubuntu-ports"
        ;;
    *)
        UBUNTU_PATH="ubuntu"
        ;;
esac

MIRROR_HOST="mirrors.aliyun.com"
changed=0

rewrite_file() {
    local source_file="$1"
    [ -f "${source_file}" ] || return 0
    [ -w "${source_file}" ] || {
        echo "[${NODE_IP}] WARN: cannot write ${source_file}; skip mirror rewrite" >&2
        return 0
    }

    local before after
    before=$(cksum "${source_file}" 2>/dev/null || true)

    # Official / overseas Ubuntu hosts -> Aliyun.
    # Keep protocol (http/https) and trailing path separators intact.
    sed -i -E \
        -e "s#(https?://)(archive|security|ports)\\.ubuntu\\.com/(ubuntu|ubuntu-ports)#\\1${MIRROR_HOST}/${UBUNTU_PATH}#g" \
        -e "s#(https?://)([a-z]{2}\\.)?archive\\.ubuntu\\.com/(ubuntu|ubuntu-ports)#\\1${MIRROR_HOST}/${UBUNTU_PATH}#g" \
        -e "s#(https?://)security\\.ubuntu\\.com/(ubuntu|ubuntu-ports)#\\1${MIRROR_HOST}/${UBUNTU_PATH}#g" \
        -e "s#(https?://)ports\\.ubuntu\\.com/(ubuntu|ubuntu-ports)#\\1${MIRROR_HOST}/ubuntu-ports#g" \
        "${source_file}" 2>/dev/null || true

    # Already on Aliyun but wrong path for ARM.
    if [ "${UBUNTU_PATH}" = "ubuntu-ports" ]; then
        sed -i -E \
            "s#(mirrors\\.aliyun\\.com)/ubuntu([ /]|$)#\\1/ubuntu-ports\\2#g" \
            "${source_file}" 2>/dev/null || true
    fi

    after=$(cksum "${source_file}" 2>/dev/null || true)
    if [ "${before}" != "${after}" ]; then
        echo "[${NODE_IP}] Ubuntu APT mirror rewritten in ${source_file} -> ${MIRROR_HOST}/${UBUNTU_PATH}"
        changed=1
    fi
}

shopt -s nullglob
for source_file in \
    "${APT_SOURCES_ROOT}/sources.list" \
    "${APT_SOURCES_ROOT}/sources.list.d"/*.list \
    "${APT_SOURCES_ROOT}/sources.list.d"/*.sources; do
    rewrite_file "${source_file}"
done
shopt -u nullglob

if [ "${changed}" = "0" ]; then
    if grep -RqsE 'archive\.ubuntu\.com|security\.ubuntu\.com|ports\.ubuntu\.com' \
        "${APT_SOURCES_ROOT}/sources.list" "${APT_SOURCES_ROOT}/sources.list.d" 2>/dev/null; then
        echo "[${NODE_IP}] WARN: official Ubuntu hosts still present after rewrite attempt" >&2
    else
        echo "[${NODE_IP}] Ubuntu APT sources already look domestic or non-Ubuntu; no rewrite needed"
    fi
fi

exit 0
