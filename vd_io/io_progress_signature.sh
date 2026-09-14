#!/usr/bin/env bash
set -euo pipefail

protected_names() {
    lsblk -nr -o NAME,PKNAME,MOUNTPOINT 2>/dev/null | awk '
        {
            parent[$1]=$2
            if ($3 != "") protected[$1]=1
        }
        END {
            changed=1
            while (changed) {
                changed=0
                for (name in protected) {
                    p=parent[name]
                    if (p != "" && !protected[p]) {
                        protected[p]=1
                        changed=1
                    }
                }
            }
            for (name in protected) print name
        }
    ' | sort -u
}

protected="$(protected_names || true)"

is_protected() {
    local dev="$1"
    printf '%s\n' "${protected}" | grep -qx -- "${dev}"
}

active_fio_devices() {
    local pid fd target name found=0
    for pid in $(pgrep -x fio 2>/dev/null || true); do
        for fd in /proc/"${pid}"/fd/*; do
            target=$(readlink -f "${fd}" 2>/dev/null || true)
            case "${target}" in
                /dev/*)
                    name=$(lsblk -ndo NAME "${target}" 2>/dev/null | head -n 1)
                    if [[ -n "${name}" ]]; then
                        printf '%s\n' "${name}"
                        found=1
                    fi
                    ;;
            esac
        done
    done
    if [[ "${found}" -eq 0 ]]; then
        # FIO may still be opening files. Restrict fallback to draid VDs instead
        # of treating unrelated physical-disk traffic as test progress.
        lsblk -dn -o NAME,TYPE 2>/dev/null | awk '$2 == "disk" && $1 ~ /^dp[0-9]+-vd[0-9]+$/ { print $1 }'
    fi
}

active_fio_devices | sort -u | while read -r dev; do
    case "${dev}" in
        loop*|ram*|sr*|fd*|md*|dm-*|zram*)
            continue
            ;;
    esac

    if is_protected "${dev}"; then
        continue
    fi

    stat_file="/sys/block/${dev}/stat"
    if [ ! -r "${stat_file}" ]; then
        continue
    fi

    awk -v dev="${dev}" '{ print dev ":" $3 ":" $7 }' "${stat_file}"
done | sort
