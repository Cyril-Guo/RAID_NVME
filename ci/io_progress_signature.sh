#!/usr/bin/env bash
set -euo pipefail

protected_names() {
    lsblk -nr -o NAME,PKNAME,MOUNTPOINT 2>/dev/null | awk '
        $3 != "" {
            print $1
            if ($2 != "") {
                print $2
            }
        }
    ' | sort -u
}

protected="$(protected_names || true)"

is_protected() {
    local dev="$1"
    printf '%s\n' "${protected}" | grep -qx -- "${dev}"
}

lsblk -dn -o NAME,TYPE 2>/dev/null | awk '$2 == "disk" { print $1 }' | while read -r dev; do
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
