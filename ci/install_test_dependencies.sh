#!/bin/bash
set -euo pipefail

qemu_env=${QEMU_VM_TARGET:-0}
need_test_deps=0

python3 -c "import pytest" >/dev/null 2>&1 || need_test_deps=1
if [ "$qemu_env" = "1" ]; then
    for tool in fio nvme lspci findmnt lsblk; do
        command -v "$tool" >/dev/null 2>&1 || need_test_deps=1
    done
fi

if [ "$need_test_deps" = "1" ]; then
    if command -v apt-get >/dev/null 2>&1; then
        export DEBIAN_FRONTEND=noninteractive
        apt_retry() {
            for attempt in 1 2 3; do
                "$@" && return 0
                echo "apt command failed, retry ${attempt}/3: $*" >&2
                sleep $((attempt * 10))
            done
            "$@"
        }
        apt_retry apt-get -o DPkg::Lock::Timeout=600 update
        if [ "$qemu_env" = "1" ]; then
            apt_retry apt-get -o DPkg::Lock::Timeout=600 install -y \
                python3-pip python3-pytest python-is-python3 \
                fio nvme-cli pciutils util-linux smartmontools sdparm \
                sysstat gawk nmap bc psmisc numactl lsscsi unzip \
                xfsprogs parted make gcc g++
        else
            apt_retry apt-get -o DPkg::Lock::Timeout=600 install -y python3-pip python3-pytest
        fi
    elif command -v dnf >/dev/null 2>&1; then
        if [ "$qemu_env" = "1" ]; then
            dnf install -y python3-pip python3-pytest fio nvme-cli pciutils util-linux \
                smartmontools sdparm sysstat gawk nmap bc psmisc numactl lsscsi unzip \
                xfsprogs parted make gcc gcc-c++
        else
            dnf install -y python3-pip python3-pytest
        fi
    elif command -v yum >/dev/null 2>&1; then
        if [ "$qemu_env" = "1" ]; then
            yum install -y python3-pip python3-pytest fio nvme-cli pciutils util-linux \
                smartmontools sdparm sysstat gawk nmap bc psmisc numactl lsscsi unzip \
                xfsprogs parted make gcc gcc-c++
        else
            yum install -y python3-pip python3-pytest
        fi
    elif command -v zypper >/dev/null 2>&1; then
        if [ "$qemu_env" = "1" ]; then
            zypper install -y python3-pip python3-pytest fio nvme-cli pciutils util-linux \
                smartmontools sdparm sysstat gawk nmap bc psmisc numactl lsscsi unzip \
                xfsprogs parted make gcc gcc-c++
        else
            zypper install -y python3-pip python3-pytest
        fi
    fi
fi

if ! python3 -c "import pytest" >/dev/null 2>&1; then
    python3 -m pip --version >/dev/null 2>&1 || python3 -m ensurepip --default-pip >/dev/null 2>&1 || true
    if python3 -m pip install --help 2>/dev/null | grep -q -- "--break-system-packages"; then
        python3 -m pip install --break-system-packages pytest
    else
        python3 -m pip install pytest
    fi
fi

if python3 -m pip --version >/dev/null 2>&1; then
    if python3 -m pip install --help 2>/dev/null | grep -q -- "--break-system-packages"; then
        python3 -m pip install --break-system-packages allure-pytest || true
    else
        python3 -m pip install allure-pytest || true
    fi
fi

python3 -c "import pytest"
if [ "$qemu_env" = "1" ]; then
    missing_tools=""
    for tool in fio nvme lspci findmnt lsblk; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            missing_tools="${missing_tools} ${tool}"
        fi
    done
    if [ -n "$missing_tools" ]; then
        echo "Missing required QEMU VM test tools after auto install:${missing_tools}" >&2
        exit 1
    fi
fi
