#!/bin/bash
set -euo pipefail

NODE_IP=${NODE_IP:-unknown}

echo "[${NODE_IP}] restore physical host RAID state after physical host test"
echo "[${NODE_IP}] unload draid module before restoring physical RAID state if loaded"
if grep -q "^draid " /proc/modules; then
    rmmod draid || modprobe -r draid
fi
if grep -q "^draid " /proc/modules; then
    echo "[${NODE_IP}] draid module is still loaded before restoring physical RAID state" >&2
    grep -i draid /proc/modules >&2 || true
    exit 1
fi

vd_ids=$(
    dpraid /c0/vall show 2>/dev/null |
    while read -r first rest; do
        case "$first" in
            */*)
                vd="${first#*/}"
                case "$vd" in
                    ""|*[!0-9]*) ;;
                    *) printf "%s\n" "$vd" ;;
                esac
                ;;
        esac
    done | sort -n -u || true
)
for vd in $vd_ids; do
    echo "[${NODE_IP}] delete existing VD after physical host test: v${vd}"
    dpraid "/c0/v${vd}" delete || true
done

slot_ids=$(
    dpraid /c0/eall/sall show 2>/dev/null |
    while read -r first rest; do
        case "$first" in
            *:*)
                slot="${first#*:}"
                case "$slot" in
                    ""|*[!0-9]*) ;;
                    *) printf "%s\n" "$slot" ;;
                esac
                ;;
        esac
    done | sort -n -u || true
)
for slot in $slot_ids; do
    echo "[${NODE_IP}] release physical disk after physical host test: s${slot}"
    dpraid "/c0/eall/s${slot}" delete || true
done

echo 1 > /sys/bus/pci/rescan || true
sleep 5
nvme list || true
