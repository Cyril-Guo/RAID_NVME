#!/bin/bash
# Install host/DUT packages needed by CI physical tests and env_prepare draid builds.
# Mirrors SMOKE driver-build deps (make/gcc/headers/kmod) plus ripgrep for
# kernel_driver portable-check (scripts/check_portable_sources.sh).
set -euo pipefail

need_test_deps=0
KERNEL_BUILD_DIR="/lib/modules/$(uname -r)/build"

fix_ubuntu_package_architectures() {
    command -v dpkg >/dev/null 2>&1 || return 0
    architecture=$(dpkg --print-architecture 2>/dev/null || true)

    if [ "${architecture}" = "amd64" ]; then
        echo "Restrict APT package indexes to native amd64; keep registered foreign architectures unchanged"
        cat > /etc/apt/apt.conf.d/99raid-nvme-native-architecture <<'APT_NATIVE_ARCH'
APT::Architecture "amd64";
APT::Architectures { "amd64"; };
APT_NATIVE_ARCH
        return 0
    fi

    case "${architecture}" in
        arm64|armhf) ;;
        *) return 0 ;;
    esac

    for source_file in \
        /etc/apt/sources.list \
        /etc/apt/sources.list.d/*.list \
        /etc/apt/sources.list.d/*.sources; do
        [ -f "${source_file}" ] || continue
        if grep -qE 'mirrors\.aliyun\.com/ubuntu([ /]|$)' "${source_file}"; then
            echo "Fix ARM Ubuntu mirror in ${source_file}: /ubuntu -> /ubuntu-ports"
            sed -i -E \
                's#(mirrors\.aliyun\.com)/ubuntu([ /]|$)#\1/ubuntu-ports\2#g' \
                "${source_file}"
        fi
    done
}

python3 -c "import pytest" >/dev/null 2>&1 || need_test_deps=1
# fio stack + draid build toolchain + portable-check (rg).
for tool in fio nvme lspci findmnt lsblk rg make gcc insmod modinfo; do
    command -v "$tool" >/dev/null 2>&1 || need_test_deps=1
done
[ -e "${KERNEL_BUILD_DIR}" ] || need_test_deps=1

if [ "$need_test_deps" = "1" ]; then
    if command -v apt-get >/dev/null 2>&1; then
        export DEBIAN_FRONTEND=noninteractive
        fix_ubuntu_package_architectures
        apt_retry() {
            for attempt in 1 2 3; do
                "$@" && return 0
                echo "apt command failed, retry ${attempt}/3: $*" >&2
                sleep $((attempt * 10))
            done
            "$@"
        }
        apt_retry apt-get -o DPkg::Lock::Timeout=600 update
        apt_retry apt-get -o DPkg::Lock::Timeout=600 install -y \
            python3-pip python3-pytest python-is-python3 \
            fio nvme-cli pciutils util-linux smartmontools sdparm \
            sysstat gawk nmap bc psmisc numactl lsscsi unzip \
            xfsprogs parted make gcc g++ \
            build-essential "linux-headers-$(uname -r)" kmod \
            ripgrep
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y python3-pip python3-pytest fio nvme-cli pciutils util-linux \
            smartmontools sdparm sysstat gawk nmap bc psmisc numactl lsscsi unzip \
            xfsprogs parted make gcc gcc-c++ \
            kernel-devel kmod ripgrep
    elif command -v yum >/dev/null 2>&1; then
        yum install -y python3-pip python3-pytest fio nvme-cli pciutils util-linux \
            smartmontools sdparm sysstat gawk nmap bc psmisc numactl lsscsi unzip \
            xfsprogs parted make gcc gcc-c++ \
            kernel-devel kmod ripgrep
    elif command -v zypper >/dev/null 2>&1; then
        zypper install -y python3-pip python3-pytest fio nvme-cli pciutils util-linux \
            smartmontools sdparm sysstat gawk nmap bc psmisc numactl lsscsi unzip \
            xfsprogs parted make gcc gcc-c++ \
            kernel-devel kmod ripgrep
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
missing_tools=""
for tool in fio nvme lspci findmnt lsblk rg make gcc insmod modinfo; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        missing_tools="${missing_tools} ${tool}"
    fi
done
if [ ! -e "${KERNEL_BUILD_DIR}" ]; then
    missing_tools="${missing_tools} kernel-build(${KERNEL_BUILD_DIR})"
fi
if [ -n "$missing_tools" ]; then
    echo "Missing required test/driver-build tools after auto install:${missing_tools}" >&2
    exit 1
fi
