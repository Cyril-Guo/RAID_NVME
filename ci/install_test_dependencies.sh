#!/bin/bash
# Install host/DUT packages needed by CI physical tests and env_prepare draid builds.
# Mirrors SMOKE driver-build deps (make/gcc/headers/kmod) plus ripgrep for
# kernel_driver portable-check (scripts/check_portable_sources.sh).
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
need_test_deps=0
KERNEL_BUILD_DIR="/lib/modules/$(uname -r)/build"

enable_failure_coredumps_early() {
    if [ -f "${SCRIPT_DIR}/enable_failure_coredumps.sh" ]; then
        echo "Enable DUT userspace coredumps (limits/sysctl/ptrace/core_pattern)"
        chmod +x "${SCRIPT_DIR}/enable_failure_coredumps.sh" 2>/dev/null || true
        NODE_IP="${NODE_IP:-unknown}" REMOTE_DIR="${REMOTE_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}" \
            "${SCRIPT_DIR}/enable_failure_coredumps.sh" || true
    fi
    if [ -f "${SCRIPT_DIR}/enable_failure_kdump.sh" ]; then
        echo "Enable DUT kdump (crashkernel / vmcore path)"
        chmod +x "${SCRIPT_DIR}/enable_failure_kdump.sh" 2>/dev/null || true
        NODE_IP="${NODE_IP:-unknown}" REMOTE_DIR="${REMOTE_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}" \
            "${SCRIPT_DIR}/enable_failure_kdump.sh" || true
    fi
    if [ -f "${SCRIPT_DIR}/enable_draid_pending_debug.sh" ]; then
        echo "Enable draid RAID1 pending debug knobs (best-effort)"
        chmod +x "${SCRIPT_DIR}/enable_draid_pending_debug.sh" 2>/dev/null || true
        NODE_IP="${NODE_IP:-unknown}" REMOTE_DIR="${REMOTE_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}" \
            "${SCRIPT_DIR}/enable_draid_pending_debug.sh" || true
    fi
}

# Always arm coredumps + kdump during dependency/env prepare, even if packages are already installed.
enable_failure_coredumps_early

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
}

ensure_ubuntu_china_mirrors() {
    SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    if [ -f "${SCRIPT_DIR}/ensure_ubuntu_china_mirrors.sh" ]; then
        chmod +x "${SCRIPT_DIR}/ensure_ubuntu_china_mirrors.sh" 2>/dev/null || true
        NODE_IP="${NODE_IP:-unknown}" bash "${SCRIPT_DIR}/ensure_ubuntu_china_mirrors.sh" || true
    fi
}

python3 -c "import pytest" >/dev/null 2>&1 || need_test_deps=1
# fio stack + draid build toolchain + portable-check (rg) + gcore (gdb).
for tool in fio nvme lspci findmnt lsblk rg make gcc insmod modinfo gcore; do
    command -v "$tool" >/dev/null 2>&1 || need_test_deps=1
done
[ -e "${KERNEL_BUILD_DIR}" ] || need_test_deps=1

if [ "$need_test_deps" = "1" ]; then
    if command -v apt-get >/dev/null 2>&1; then
        export DEBIAN_FRONTEND=noninteractive
        ensure_ubuntu_china_mirrors
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
            ripgrep gdb kdump-tools kexec-tools makedumpfile
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y python3-pip python3-pytest fio nvme-cli pciutils util-linux \
            smartmontools sdparm sysstat gawk nmap bc psmisc numactl lsscsi unzip \
            xfsprogs parted make gcc gcc-c++ \
            kernel-devel kmod ripgrep gdb kexec-tools makedumpfile
    elif command -v yum >/dev/null 2>&1; then
        yum install -y python3-pip python3-pytest fio nvme-cli pciutils util-linux \
            smartmontools sdparm sysstat gawk nmap bc psmisc numactl lsscsi unzip \
            xfsprogs parted make gcc gcc-c++ \
            kernel-devel kmod ripgrep gdb kexec-tools makedumpfile
    elif command -v zypper >/dev/null 2>&1; then
        zypper install -y python3-pip python3-pytest fio nvme-cli pciutils util-linux \
            smartmontools sdparm sysstat gawk nmap bc psmisc numactl lsscsi unzip \
            xfsprogs parted make gcc gcc-c++ \
            kernel-devel kmod ripgrep gdb kexec-tools makedumpfile
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

# gdb/gcore is required for failure bundles but should not hard-fail older images
# until packages are refreshed; warn only.
if ! command -v gcore >/dev/null 2>&1; then
    echo "WARN: gcore missing after dependency install; failure gcore dumps will be skipped" >&2
fi

# Re-apply after package install (gdb may have just landed; sysctl may have been reset).
enable_failure_coredumps_early
