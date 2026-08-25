#!/usr/bin/env bash
# Enable kdump on the DUT so kernel panic/hard hang can produce vmcore.
# Best-effort: never fails the caller. Full activation often needs one reboot
# after crashkernel= is added to the boot cmdline.
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/.." && pwd)
REMOTE_DIR=${REMOTE_DIR:-${REPO_ROOT}}
NODE_IP=${NODE_IP:-unknown}
KDUMP_DIR="${REMOTE_DIR}/failure_bundles/kdump"
STATUS_FILE="${REMOTE_DIR}/failure_bundles/kdump_status.txt"
REBOOT_FLAG="${REMOTE_DIR}/failure_bundles/kdump_reboot_required.txt"
# Reserved memory for the dump capture kernel (not the full RAM dump size).
CRASHKERNEL_CMDLINE=${CRASHKERNEL_CMDLINE:-crashkernel=512M}

mkdir -p "${KDUMP_DIR}" /var/crash 2>/dev/null || true
: >"${STATUS_FILE}"

log() {
    printf '[%s] %s\n' "${NODE_IP}" "$*" | tee -a "${STATUS_FILE}"
}

have_crashkernel() {
    if grep -qw crashkernel /proc/cmdline 2>/dev/null; then
        return 0
    fi
    if [ -d /sys/kernel/kexec_crash_size ] || [ -r /sys/kernel/kexec_crash_size ]; then
        size=$(cat /sys/kernel/kexec_crash_size 2>/dev/null || echo 0)
        [ "${size}" != "0" ] && [ -n "${size}" ]
        return $?
    fi
    return 1
}

install_kdump_packages() {
    if command -v apt-get >/dev/null 2>&1; then
        export DEBIAN_FRONTEND=noninteractive
        if [ -f "${SCRIPT_DIR}/ensure_ubuntu_china_mirrors.sh" ]; then
            NODE_IP="${NODE_IP}" bash "${SCRIPT_DIR}/ensure_ubuntu_china_mirrors.sh" >/dev/null 2>&1 || true
        fi
        apt-get -o DPkg::Lock::Timeout=600 update >/dev/null 2>&1 || true
        apt-get -o DPkg::Lock::Timeout=600 install -y kdump-tools kexec-tools crash makedumpfile 2>>"${STATUS_FILE}" || true
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y kexec-tools crash makedumpfile 2>>"${STATUS_FILE}" || true
    elif command -v yum >/dev/null 2>&1; then
        yum install -y kexec-tools crash makedumpfile 2>>"${STATUS_FILE}" || true
    elif command -v zypper >/dev/null 2>&1; then
        zypper install -y kexec-tools crash makedumpfile 2>>"${STATUS_FILE}" || true
    fi
}

configure_ubuntu_kdump() {
    local conf=/etc/default/kdump-tools
    if [ -f "${conf}" ]; then
        sed -i 's/^USE_KDUMP=.*/USE_KDUMP=1/' "${conf}" 2>/dev/null || true
        if grep -q '^USE_KDUMP=' "${conf}"; then
            :
        else
            echo 'USE_KDUMP=1' >>"${conf}"
        fi
        # Prefer local path; keep /var/crash as well via KDUMP_COREDIR if supported.
        if grep -q '^KDUMP_COREDIR=' "${conf}" 2>/dev/null; then
            sed -i "s|^KDUMP_COREDIR=.*|KDUMP_COREDIR=\"${KDUMP_DIR}\"|" "${conf}" 2>/dev/null || true
        else
            echo "KDUMP_COREDIR=\"${KDUMP_DIR}\"" >>"${conf}"
        fi
        log "configured ${conf} USE_KDUMP=1 COREDIR=${KDUMP_DIR}"
    fi
}

configure_rhel_kdump() {
    local conf=/etc/kdump.conf
    if [ -f "${conf}" ]; then
        if grep -qE '^path ' "${conf}"; then
            sed -i "s|^path .*|path ${KDUMP_DIR}|" "${conf}" 2>/dev/null || true
        else
            echo "path ${KDUMP_DIR}" >>"${conf}"
        fi
        # Keep a compressed dump to reduce size (still large).
        if ! grep -qE '^core_collector ' "${conf}"; then
            echo 'core_collector makedumpfile -l --message-level 1 -d 31' >>"${conf}"
        fi
        if ! grep -qE '^default ' "${conf}"; then
            echo 'default reboot' >>"${conf}"
        fi
        log "configured ${conf} path=${KDUMP_DIR}"
    fi
}

ensure_crashkernel_cmdline() {
    local grub_d=/etc/default/grub.d
    local grub_file=/etc/default/grub
    local dropin="${grub_d}/99-raid-nvme-kdump.cfg"
    local changed=0

    if have_crashkernel; then
        log "crashkernel already present: $(grep -o 'crashkernel=[^ ]*' /proc/cmdline 2>/dev/null || cat /sys/kernel/kexec_crash_size 2>/dev/null)"
        rm -f "${REBOOT_FLAG}" 2>/dev/null || true
        return 0
    fi

    if [ -d "${grub_d}" ] && [ -w "${grub_d}" ]; then
        cat >"${dropin}" <<EOF
# Managed by RAID_NVME ci/enable_failure_kdump.sh
GRUB_CMDLINE_LINUX_DEFAULT="\${GRUB_CMDLINE_LINUX_DEFAULT} ${CRASHKERNEL_CMDLINE}"
EOF
        changed=1
        log "wrote ${dropin} (${CRASHKERNEL_CMDLINE})"
    elif [ -f "${grub_file}" ] && [ -w "${grub_file}" ]; then
        if ! grep -q 'crashkernel=' "${grub_file}" 2>/dev/null; then
            if grep -q '^GRUB_CMDLINE_LINUX_DEFAULT=' "${grub_file}"; then
                sed -i "s|^GRUB_CMDLINE_LINUX_DEFAULT=\"\\(.*\\)\"|GRUB_CMDLINE_LINUX_DEFAULT=\"\\1 ${CRASHKERNEL_CMDLINE}\"|" "${grub_file}" \
                    || sed -i "s|^GRUB_CMDLINE_LINUX_DEFAULT='\\(.*\\)'|GRUB_CMDLINE_LINUX_DEFAULT='\\1 ${CRASHKERNEL_CMDLINE}'|" "${grub_file}" \
                    || true
            else
                echo "GRUB_CMDLINE_LINUX_DEFAULT=\"${CRASHKERNEL_CMDLINE}\"" >>"${grub_file}"
            fi
            changed=1
            log "updated ${grub_file} with ${CRASHKERNEL_CMDLINE}"
        fi
    else
        log "WARN: cannot update grub cmdline for crashkernel"
        return 0
    fi

    if [ "${changed}" = "1" ]; then
        if command -v update-grub >/dev/null 2>&1; then
            update-grub >>"${STATUS_FILE}" 2>&1 || true
        elif command -v grub2-mkconfig >/dev/null 2>&1; then
            grub2-mkconfig -o /boot/grub2/grub.cfg >>"${STATUS_FILE}" 2>&1 \
                || grub2-mkconfig -o /boot/efi/EFI/*/grub.cfg >>"${STATUS_FILE}" 2>&1 \
                || true
        fi
        printf '%s\n' \
            "kdump crashkernel cmdline updated; reboot DUT once to activate reservation" \
            "CRASHKERNEL=${CRASHKERNEL_CMDLINE}" \
            "NODE_IP=${NODE_IP}" \
            "TIME=$(date -Is 2>/dev/null || date)" \
            >"${REBOOT_FLAG}"
        log "REBOOT REQUIRED for crashkernel reservation (${REBOOT_FLAG})"
    fi
}

enable_kdump_service() {
    if command -v systemctl >/dev/null 2>&1; then
        systemctl enable kdump.service 2>/dev/null \
            || systemctl enable kdump-tools.service 2>/dev/null \
            || systemctl enable kdump.service 2>/dev/null \
            || true
        if have_crashkernel; then
            systemctl restart kdump.service 2>/dev/null \
                || systemctl restart kdump-tools.service 2>/dev/null \
                || true
            systemctl start kdump.service 2>/dev/null \
                || systemctl start kdump-tools.service 2>/dev/null \
                || true
        else
            log "skip kdump service start until crashkernel is active (reboot first)"
        fi
        systemctl is-active kdump.service 2>/dev/null | tee -a "${STATUS_FILE}" || true
        systemctl is-active kdump-tools.service 2>/dev/null | tee -a "${STATUS_FILE}" || true
        systemctl status kdump.service --no-pager -l 2>/dev/null | head -n 40 >>"${STATUS_FILE}" || true
        systemctl status kdump-tools.service --no-pager -l 2>/dev/null | head -n 40 >>"${STATUS_FILE}" || true
    fi
    if command -v kdump-config >/dev/null 2>&1; then
        kdump-config show >>"${STATUS_FILE}" 2>&1 || true
        kdump-config load >>"${STATUS_FILE}" 2>&1 || true
    fi
}

{
    echo "=== enable_failure_kdump start $(date -Is 2>/dev/null || date) ==="
    echo "REMOTE_DIR=${REMOTE_DIR}"
    echo "KDUMP_DIR=${KDUMP_DIR}"
    echo "cmdline=$(cat /proc/cmdline 2>/dev/null || true)"
} >>"${STATUS_FILE}"

log "install kdump packages (kexec-tools / kdump-tools)"
install_kdump_packages
configure_ubuntu_kdump
configure_rhel_kdump
ensure_crashkernel_cmdline
enable_kdump_service

{
    echo
    echo "=== summary ==="
    echo "have_crashkernel=$(have_crashkernel && echo yes || echo no)"
    echo "kdump_dir=${KDUMP_DIR}"
    echo "var_crash=$(ls -la /var/crash 2>/dev/null | head -n 20 || true)"
    echo "NOTE: vmcore size is roughly physical RAM (tens~hundreds of GB)."
    echo "NOTE: after first-time crashkernel change, reboot DUT once."
} >>"${STATUS_FILE}"

log "kdump enable done; status -> ${STATUS_FILE}"
exit 0
