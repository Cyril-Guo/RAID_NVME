#!/bin/bash
set -euo pipefail

NODE_IP=${NODE_IP:-unknown}

# Pre-test cleanup: clear leftover VDs/slots after dpraid/draid are ready.
# Keep draid loaded so the upcoming smoke test can use it immediately.
echo "[${NODE_IP}] restore RAID state before test (clear leftover VD/PD)"

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
    echo "[${NODE_IP}] delete existing VD before test: v${vd}"
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
    echo "[${NODE_IP}] release physical disk before test: s${slot}"
    dpraid "/c0/eall/s${slot}" delete || true
done

echo 1 > /sys/bus/pci/rescan || true
sleep 5
nvme list || true
