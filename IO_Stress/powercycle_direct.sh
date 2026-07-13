#!/bin/bash
if [ -z "$BASH_VERSION" ]; then
    exec bash "$0" "$@"
fi

set -o pipefail
export LANG=C.UTF-8
export LC_ALL=C.UTF-8

cd "$(dirname "$0")"

chmod +x lib/* run_fio.sh >/dev/null 2>&1 || true
. lib/global_variable.sh
. lib/arguments.sh
. lib/init.sh
. lib/common.sh
. lib/fio.sh

arguments_parse "$@"
check_arguments

if [[ "$item" != "REBOOT" && "$item" != "DC" ]]; then
    echo "powercycle_direct.sh only supports reboot/dc, got item=$item"
    exit 2
fi

export POWER_CYCLE_FORCE_ONCE=1

echo "POWER_CYCLE_DIRECT_START item=$item LOOP=$LOOP flag=$flag disks=${specified_disk:-null}"
intializer
info_check

bash ./run_fio.sh "$item" "$check" "$bmc_reset" "$flag" "$delay" "$mode" "$wait" "$port" "$server_ip" "$LOOP" "$acserverport" "$safe" "$sysStaticIP" "$blackBoxStaticIP" "$runtime" "$filename" "$fs_type" "$disk_mode" "$specified_disk" "$remote" "$mix_io" "$log_interval"
