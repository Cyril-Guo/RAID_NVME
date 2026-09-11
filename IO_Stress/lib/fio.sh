#!/bin/bash

arguments_accept()
{
    item=$1
    check=$2
    bmc_reset=$3
    flag=$4
    delay=$5
    mode=$6
    wait=$7
    port=$8
    server_ip=$9
    LOOP=${10}
    acserverport=${11}
    safe=${12}
    sysStaticIP=${13}
    blackBoxStaticIP=${14}
    runtime=${15}
    filename=${16}
    fs_type=${17}
    disk_mode=${18}
    specified_disk=${19}
    remote=${20}
    mix_io=${21}
    log_interval=${22}
}

_FIO_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "${_FIO_LIB_DIR}/fio_powercycle.sh"
. "${_FIO_LIB_DIR}/fio_verify.sh"

# Guard so we only fire one live failure-bundle per FIO watchdog session.
FIO_EIO_BUNDLE_TRIGGERED="${FIO_EIO_BUNDLE_TRIGGERED:-0}"
# Background collect by default so watchdog idle timer is not blocked by gcore/tar.
FIO_LIVE_BUNDLE_BG="${FIO_LIVE_BUNDLE_BG:-1}"

# Walk up from known roots looking for powercycle/collect_failure_bundle.sh.
find_raid_nvme_repo_root() {
    local base d i
    for base in \
        "${REMOTE_DIR:-}" \
        "${RAID_NVME_CASE_ROOT:-}" \
        "${RAID_NVME_REPO_ROOT:-}" \
        "${Cur_Dir:-}" \
        "${_FIO_LIB_DIR}/../.." \
        "$(pwd)"
    do
        [ -n "${base}" ] || continue
        d=$(cd "${base}" 2>/dev/null && pwd) || continue
        for i in 1 2 3 4 5 6; do
            if [ -f "${d}/powercycle/collect_failure_bundle.sh" ]; then
                printf '%s\n' "${d}"
                return 0
            fi
            [ "${d}" = "/" ] && break
            d=$(dirname "${d}")
        done
    done
    return 1
}

fio_log_has_eio() {
    local log_file="$1"
    [ -n "${log_file}" ] && [ -f "${log_file}" ] || return 1
    grep -Eq \
        'Input/output error|I/O error|error=Input/output error|err=[[:space:]]*5([^0-9]|$)|errno=5([^0-9]|$)|EIO' \
        "${log_file}" 2>/dev/null
}

_fio_safe_token() {
    # Keep in sync with collect_failure_bundle.sh SAFE_KEY sanitization.
    printf '%s' "${1:-unknown}" | tr -c 'A-Za-z0-9._-' '_'
}

# Best-effort immediate failure bundle while FIO may still be alive after EIO.
# Default: spawn in background so the FIO idle watchdog keeps ticking.
trigger_live_failure_bundle() {
    local reason="${1:-fio_eio_live}"
    local repo_root script run_key remote_dir node_ip
    local safe_key log_file pending_file lock_file lock_fd bg_mode collect_pid

    node_ip="${NODE_IP:-${TARGET_IP:-unknown}}"

    if [ "${FIO_EIO_BUNDLE_TRIGGERED}" = "1" ] && [ "${FIO_FORCE_BUNDLE:-0}" != "1" ]; then
        echo "$(date '+%F %T') [FIO] live failure bundle already triggered; skip (${reason})" \
            | tee -a "${Result_Dir:-/tmp}/result.log" 2>/dev/null || true
        return 0
    fi

    repo_root=$(find_raid_nvme_repo_root) || {
        echo "$(date '+%F %T') [FIO] WARN: cannot locate powercycle/collect_failure_bundle.sh; skip live bundle" \
            | tee -a "${Result_Dir:-/tmp}/result.log" 2>/dev/null || true
        return 0
    }
    script="${repo_root}/powercycle/collect_failure_bundle.sh"
    run_key="${RAID_NVME_RUN_KEY:-${FIO_LAST_CONFIG:-fio_live}}"
    remote_dir="${REMOTE_DIR:-${repo_root}}"
    safe_key=$(_fio_safe_token "${run_key}")
    mkdir -p "${remote_dir}/failure_bundles" 2>/dev/null || true
    log_file="${remote_dir}/failure_bundles/live_bundle_${safe_key}.log"
    pending_file="${remote_dir}/failure_bundles/live_collect_pending_${safe_key}.txt"
    lock_file="${remote_dir}/failure_bundles/live_collect_${safe_key}.lock"
    if command -v flock >/dev/null 2>&1; then
        exec {lock_fd}>"${lock_file}" || return 0
        if ! flock -n "${lock_fd}"; then
            echo "$(date '+%F %T') [FIO] live failure bundle collection already active; skip (${reason})" \
                | tee -a "${Result_Dir:-/tmp}/result.log" 2>/dev/null || true
            return 0
        fi
    fi
    FIO_EIO_BUNDLE_TRIGGERED=1
    bg_mode="${FIO_LIVE_BUNDLE_BG:-1}"

    {
        echo "started=$(date -Is 2>/dev/null || date)"
        echo "reason=${reason}"
        echo "run_key=${run_key}"
        echo "repo_root=${repo_root}"
        echo "remote_dir=${remote_dir}"
        echo "bg=${bg_mode}"
    } >"${pending_file}" 2>/dev/null || true

    echo "$(date '+%F %T') [FIO] triggering IMMEDIATE failure bundle reason=${reason} repo=${repo_root} bg=${bg_mode} log=${log_file}" \
        | tee -a "${Result_Dir:-/tmp}/result.log" 2>/dev/null || true

    if [ "${bg_mode}" = "1" ]; then
        (
            cd "${repo_root}" || exit 0
            {
                echo "=== live collect start $(date -Is 2>/dev/null || date) reason=${reason} ==="
                NODE_IP="${node_ip}" \
                REMOTE_DIR="${remote_dir}" \
                RUN_KEY="${run_key}" \
                BUNDLE_REASON="${reason}" \
                bash "${script}"
                echo "=== live collect end rc=$? $(date -Is 2>/dev/null || date) ==="
            } >>"${log_file}" 2>&1
            rm -f "${pending_file}" 2>/dev/null || true
        ) &
        collect_pid=$!
        echo "pid=${collect_pid}" >>"${pending_file}" 2>/dev/null || true
        echo "$(date '+%F %T') [FIO] live failure bundle spawned pid=${collect_pid}" \
            | tee -a "${Result_Dir:-/tmp}/result.log" 2>/dev/null || true
    else
        (
            cd "${repo_root}" || exit 0
            {
                echo "=== live collect start $(date -Is 2>/dev/null || date) reason=${reason} ==="
                NODE_IP="${node_ip}" \
                REMOTE_DIR="${remote_dir}" \
                RUN_KEY="${run_key}" \
                BUNDLE_REASON="${reason}" \
                bash "${script}"
                echo "=== live collect end rc=$? $(date -Is 2>/dev/null || date) ==="
            } >>"${log_file}" 2>&1
        ) || true
        rm -f "${pending_file}" 2>/dev/null || true
    fi
}

collect_log()
{
	echo "**********" `date +%m-%d" "%H:%M:%S` "Collecting logs **********"
	mce_log="/var/log/mcelog"
	messages_log="/var/log/messages"
	# Ubuntu uses syslog instead of messages
    if [ -f /etc/os-release ] && grep -iq "Ubuntu" /etc/os-release ; then
        messages_log="/var/log/syslog"
    fi
	dmesg_log="/var/log/dmesg"

    # Use timeout bash -c to ensure redirection doesn't hang shell
    # Use loop number in filename to preserve history (Plan B)
    local suffix="loop_${loop:-unknown}"

	if [ -f "$mce_log" ]; then
		echo "  - Collecting mcelog..."
		timeout 30 bash -c "cat '$mce_log' > '$SystemLog/mce_${suffix}.log'" 2>/dev/null
	fi
    if [ -f "$messages_log" ]; then
		echo "  - Collecting messages/syslog..."
	    timeout 30 bash -c "cat '$messages_log' > '$SystemLog/messages_${suffix}.log'" 2>/dev/null
    fi
	echo "  - Collecting dmesg..."
    if [[ "$item" == "REBOOT" || "$item" == "DC" ]]; then
        # Keep a labeled per-loop file + rolling summary for power-cycle tests.
        collect_powercycle_dmesg
    else
	    timeout 30 bash -c "dmesg -T > '$SystemLog/dmesg_${suffix}.log'" 2>/dev/null
    fi

    # Add IPMI SEL collection as requested
    if command -v ipmitool >/dev/null 2>&1; then
        echo "  - Collecting IPMI SEL..."
        timeout 30 bash -c "ipmitool sel list > '$SystemLog/ipmi_sel_${suffix}.log'" 2>/dev/null
    fi

    echo "********** Log collection complete (Suffix: ${suffix}) **********"
}

test_end()
{
    # Optional exit status (default 0). MachineCheck STOP should pass a non-zero rc.
    local rc=${1:-0}
    echo ""
    echo "=========================================="
    echo "********** ALL TESTS COMPLETE **********"
    echo "=========================================="
    echo "********** NVME RAID Test Engine Exit **********"
    exit "${rc}"
}








function close_mount(){
    sleep 10
    for ((i=0; i<${#add_disks[*]}; i++));do
        assert_not_system_disk "${add_disks[$i]}" "close mount" "allow-mounted" || return $?
        umount /dev/${add_disks[$i]}
        if [ $? -ne 0 ];then
            lsof /dev/${add_disks[$i]} | awk '{print $2}' | xargs kill -9
        fi
    done
}


function gen_config_file()
{


    mode_rs=`sed -n "$line" $File_Dir/$filename |awk -F "," '{print $2}'`
    mode_rw=`sed -n "$line" $File_Dir/$filename |awk -F "," '{print $3}'`
    read_percentage=`sed -n "$line" $File_Dir/$filename |awk -F "," '{print $3}'`
    blocksize=`sed -n "$line" $File_Dir/$filename |awk -F "," '{print $1}'`
    # Skip commented lines or empty lines
    if [[ $blocksize =~ ^# ]] || [[ -z $blocksize ]]; then
        return
    fi
    iodepth=`sed -n "$line"  $File_Dir/$filename |awk -F "," '{print $4}'`
    run_time=`sed -n "$line" $File_Dir/$filename |awk -F "," '{print $5}'`
    numjobs=`sed -n "$line" $File_Dir/$filename |awk -F "," '{print $6}'`
    offset=`sed -n "$line" $File_Dir/$filename |awk -F "," '{print $7}'`
    io_size=`sed -n "$line" $File_Dir/$filename |awk -F "," '{print $8}'`
    verify_mode=`sed -n "$line" $File_Dir/$filename |awk -F "," '{print $9}'`
    verify_type=`sed -n "$line" $File_Dir/$filename |awk -F "," '{print $10}'`
    check_="$blocksize"
    if [[ $check_ == "End" ]];then
        echo "Job files are under $Config_Dir"
        echo ""
        return
    fi

    if [[ $mode_rs -eq 100 ]];then
        mode_rs=R
    elif [[ $mode_rs -eq 0 ]];then
        mode_rs=S
    else
        echo ""
    fi

    if [[ $mode_rw -eq 100 ]];then
        mode_rw=READ
    elif [[ $mode_rw -eq 0 ]];then
        mode_rw=WRITE
    else
        mode_rw=MIX
    fi

    if [ "$mode_rs" = "R" ] && [ "$mode_rw" = "READ" ];then
        mode_=randread
    fi

    if [[ $mode_rs = R ]] && [[ $mode_rw = WRITE ]];then
        mode_=randwrite
    fi

    if [[ $mode_rs = R ]] && [[ $mode_rw = MIX ]];then
        mode_=randrw
    fi

    if [[ $mode_rs = S ]] && [[ $mode_rw = READ ]];then
        mode_=read
    fi

    if [[ $mode_rs = S ]] && [[ $mode_rw = WRITE ]];then
        mode_=write
    fi
    
    if [[ $mode_rs = S ]] && [[ $mode_rw = MIX ]]; then
            mode_=rw
    fi

    if [[ $mode_rw == MIX ]];then
        sed -i '/rwmixread/d' $Cur_Dir/configuration.tmp
#        sed -i '/rw/d' $Cur_Dir/configuration.tmp
        sed -i '8i rwmixread=read_percentage' $Cur_Dir/configuration.tmp
    fi

    if [[ $mode_rw != MIX ]];then
        sed -i '/rwmixread/d' $Cur_Dir/configuration.tmp
    fi

        count=` expr $line_t - 1 `
        blocksize_label="$blocksize"
        if [[ "$blocksize" == bssplit=* ]]; then
            blocksize_label="bssplit"
        fi
        config_file="$count-$mode_-$blocksize_label-$iodepth-$run_time.log"

        sed -i '/randrepeat/d' $Cur_Dir/configuration.tmp
        sed -i '/norandommap/d' $Cur_Dir/configuration.tmp
        sed -i '/ramp_time/d' $Cur_Dir/configuration.tmp
        fio_verify_strip_config_directives
        if [[ $disk_mode == "SUBALL" ]];then
            sed -i '/group_reporting/d' $Cur_Dir/configuration.tmp
        fi

        if [[ $item =~ "STRESS" ]];then

            sed -i "9i randrepeat=0"  $Cur_Dir/configuration.tmp
            sed -i "9i norandommap"  $Cur_Dir/configuration.tmp
            sed -i "9i ramp_time=5" $Cur_Dir/configuration.tmp
        fi
        if [[ -n "$verify_mode" ]]; then
            fio_verify_apply_mode_options "$verify_mode" "$run_time"
        fi
        if [[ "$blocksize" == bssplit=* ]]; then
            sed "s#^bs=config_blocksize#${blocksize}#" \
                $Cur_Dir/configuration.tmp > $Config_Dir/$config_file
        else
            sed "s/config_blocksize/$blocksize/" \
                $Cur_Dir/configuration.tmp > $Config_Dir/$config_file
        fi
        sed -i "s/config_mode/$mode_/" $Config_Dir/$config_file
        sed -i "s/run_time/$run_time/" $Config_Dir/$config_file
        sed -i "s/config_iodepth/$iodepth/" $Config_Dir/$config_file
        sed -i "s/num_jobs/$numjobs/" $Config_Dir/$config_file
        sed -i "s/read_percentage/$read_percentage/" $Config_Dir/$config_file
        if [[ -n "$verify_mode" ]]; then
            fio_verify_substitute_job_placeholders "$offset" "$io_size" "$verify_type" "$config_file"
        else
            sed -i "s/off_set/${offset}%/" $Config_Dir/$config_file
        fi
	    sed -i "s/config_log_avg_msec/$log_interval/"  $Config_Dir/$config_file


    
}

function configure()
{
    echo "**********" `date +%m-%d" "%H:%M:%S` "Generating Config Files**********"


    check_="START"
    line_t=2
    until [[ $check_ == "End" ]]
    do
        line=`echo "$line_t"p`
        gen_config_file
        line_t=` expr $line_t + 1 `
    done
    cd $Config_Dir
    config_files=`ls -p | grep -v /`
    echo $config_files
    cd - >/dev/null
}









function set_Disk()
{
    cp $Cur_Dir/configuration $Cur_Dir/configuration.tmp
    if [[ $disk_mode == ALL || $disk_mode == SUBALL ]];then
        if [[ $item == REBOOT || $item == DC ]];then
            # 仅对非系统盘的裸设备下发 IO（系统盘已在 do_fio 中被排除，不再对系统盘做任何 IO）
            for str in ${disk[@]}
            do
                assert_not_system_disk "$str" "generate fio config" || return $?
                Hard_Disk="/dev/"$str
                echo "["$str"]" >>$Cur_Dir/configuration.tmp
                echo "filename="$Hard_Disk >>$Cur_Dir/configuration.tmp
                echo "size=100%" >>$Cur_Dir/configuration.tmp
            done
        fi
        swapoff -a
    fi  
}

function div()
{
    a=$1
    if [[ "$a" =~ "KB" ]];then
        bw1=`echo $a |sed 's/K//g' |sed 's/M//g'|sed 's/B//g'`
        bw2=`echo $bw1 |awk '{printf "%.2lf",$1/1024}'`MB
        echo $bw2
    elif [[ "$a" =~ "MB" ]];then
        bw1=`echo $a |sed 's/M//g'|sed 's/B//g'|sed 's/\///g'|sed 's/s//g'`
        bw2=`echo $bw1`MB
        echo $bw2
    elif [[ "$a" =~ "KiB" ]];then
        bw1=`echo $a |sed 's/K//g'|sed 's/i//g'|sed 's/B//g'|sed 's/\///g'|sed 's/s//g'`
        bw2=`echo $bw1 |awk '{printf "%.2lf",$1/1024}'`MiB
        #bw2=`echo $bw1`KiB
        echo $bw2
    elif [[ "$a" =~ "MiB" ]];then
        bw1=`echo $a |sed 's/M//g'|sed 's/i//g'|sed 's/B//g'|sed 's/\///g'|sed 's/s//g'`
        bw2=`echo $bw1`MiB
        echo $bw2
    elif [[ "$a" =~ "GiB" ]];then
        bw1=`echo $a |sed 's/G//g'|sed 's/i//g'|sed 's/B//g'|sed 's/\///g'|sed 's/s//g'`
        bw2=`echo $bw1 |awk '{printf "%.2lf",$1*1024}'`MiB
        #bw2=`echo $bw1`KiB
        echo $bw2
    else
        bw1=`echo $a |sed 's/K//g' |sed 's/M//g'|sed 's/i//g'|sed 's/B//g'`
        bw2=`echo $bw1 |awk '{printf "%.2lf",$1/1048576}'`MiB
        echo $bw2
    fi

}
function if_sdx()
{
    line=$1
    os_disk=`sed -n $line tmp.log|awk '{print $1}'`

    if [[ $os_disk =~ sd ]];then
      return 1
    else
      return 0
    fi
}

get_system_disk()
{
    local devices=""
    local mount_point
    local source
    local direct_disks

    for mount_point in / /boot /boot/efi; do
        source=$(findmnt -nvo SOURCE "$mount_point" 2>/dev/null | sed 's/\[.*\]//' | head -n 1)
        [[ -n "$source" ]] && devices="$devices $source"
    done

    devices="$devices $(lsblk -nr -o NAME,PKNAME,MOUNTPOINT 2>/dev/null | awk '$3=="/" || $3=="/boot" || $3=="/boot/efi" {print $1" "$2}')"
    system_disk_sources=$(echo "$devices" | xargs)

    direct_disks=$(extract_parent_disks_from_words $devices | awk 'NF && !seen[$0]++' | xargs)
    [[ -n "$direct_disks" ]] && system_disk="$direct_disks"

    if [[ -z "$system_disk" ]]; then
        system_disk=$(for device in $devices; do
            normalize_system_disk "$device" || true
        done | awk 'NF && !seen[$0]++' | xargs)
    fi
    system_block_devices=$(collect_system_block_devices "$devices")
}

disk_is_system()
{
    local disk_name="$1"
    local block_name
    local normalized
    local item
    block_name=$(normalize_block_name "$disk_name")
    normalized=$(normalize_system_disk "$disk_name" | head -n 1)
    for item in $system_block_devices; do
        [[ -n "$block_name" && "$block_name" == "$item" ]] && return 0
    done
    for item in $system_disk; do
        [[ "$disk_name" == "$item" ]] && return 0
        [[ -n "$block_name" && "$block_name" == "$item" ]] && return 0
        [[ -n "$normalized" && "$normalized" == "$item" ]] && return 0
    done
    return 1
}

assert_not_system_disk()
{
    local disk_name="$1"
    local action="$2"
    local mount_policy="$3"
    if disk_is_system "$disk_name"; then
        echo "ERROR: Refuse to ${action:-use disk} on system disk or system-related partition [$disk_name], detected system disk(s): [$system_disk], protected block devices: [$system_block_devices]."
        return 1
    fi
    if [[ "$mount_policy" != "allow-mounted" ]] && device_has_mountpoint "$disk_name"; then
        echo "ERROR: Refuse to ${action:-use disk} on mounted block device or disk with mounted child [$disk_name]."
        return 1
    fi
    return 0
}

normalize_block_name()
{
    local device="$1"
    echo "$device" | sed 's#^/dev/##' | sed 's#^mapper/##'
}

extract_parent_disks_from_words()
{
    printf '%s\n' "$@" | awk '
        {
            device=$1
            sub("^/dev/", "", device)
            sub("^mapper/", "", device)
            if (device ~ /^(sd|vd|xvd|hd)[a-z]+[0-9]*$/) {
                sub(/[0-9]+$/, "", device)
                print device
            } else if (device ~ /^nvme[0-9]+n[0-9]+p?[0-9]*$/) {
                sub(/p[0-9]+$/, "", device)
                print device
            }
        }
    '
}

extract_parent_disk()
{
    extract_parent_disks_from_words "$1" | head -n 1
}

normalize_system_disk()
{
    local device="$1"
    local parent=""
    local current=""

    device=$(normalize_block_name "$device")
    [[ -z "$device" ]] && return

    if [[ "$device" =~ ^((sd|vd|xvd|hd)[a-z]+)[0-9]*$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return
    fi

    if [[ "$device" =~ ^(nvme[0-9]+n[0-9]+)(p[0-9]+)?$ ]]; then
        echo "${BASH_REMATCH[1]}"
        return
    fi

    current="$device"
    while [[ -n "$current" ]]; do
        parent=$(lsblk -nr -o NAME,PKNAME 2>/dev/null | awk -v name="$current" '$1==name {print $2; exit}')
        [[ -z "$parent" ]] && return 0
        if [[ "$parent" =~ ^((sd|vd|xvd|hd)[a-z]+)[0-9]*$ ]]; then
            echo "${BASH_REMATCH[1]}"
            return
        fi
        if [[ "$parent" =~ ^(nvme[0-9]+n[0-9]+)(p[0-9]+)?$ ]]; then
            echo "${BASH_REMATCH[1]}"
            return
        fi
        current="$parent"
    done
    return 0
}

collect_system_block_devices()
{
    local mounted_devices="$1"
    {
        for device in $mounted_devices $system_disk; do
            normalize_block_name "$device"
        done
        lsblk -nr -o NAME,PKNAME 2>/dev/null | awk -v disks="$system_disk" '
            BEGIN {
                split(disks, disk_list, " ")
                for (i in disk_list) {
                    if (disk_list[i] != "") protected[disk_list[i]]=1
                }
            }
            {
                name=$1
                parent=$2
                if (protected[name] || protected[parent]) {
                    protected[name]=1
                    print name
                }
            }
        '
    } | awk 'NF && !seen[$0]++' | xargs
}

device_has_mountpoint()
{
    local disk_name="$1"
    local block_name
    block_name=$(normalize_block_name "$disk_name")
    [[ -z "$block_name" ]] && return 1

    lsblk -nr -o NAME,PKNAME,MOUNTPOINT 2>/dev/null | awk -v name="$block_name" '
        $1 == name && $3 != "" {found=1}
        $2 == name && $3 != "" {found=1}
        END {exit found ? 0 : 1}
    '
}

specified_disk_contains_system()
{
    local disk_name
    local old_ifs="$IFS"
    IFS=", "
    for disk_name in $specified_disk; do
        if disk_is_system "$disk_name"; then
            IFS="$old_ifs"
            return 0
        fi
    done
    IFS="$old_ifs"
    return 1
}

validate_test_disks()
{
    local disk_name
    local old_ifs="$IFS"
    IFS=", "
    for disk_name in $test_disk; do
        [[ -z "$disk_name" ]] && continue
        assert_not_system_disk "$disk_name" "run fio" || {
            IFS="$old_ifs"
            return 1
        }
    done
    IFS="$old_ifs"
    return 0
}

select_auto_test_disks()
{
    local candidates=""
    local fallback=""

    # In this environment the data devices used by draid tests are dp*-vd*.
    # Prefer them when FIO_DISKS is empty so physical NVMe disks are not hit directly.
    candidates=$(lsblk -dn -o NAME,TYPE | awk '$2=="disk"{print $1}' | grep -E '^dp[0-9]+-vd[0-9]+$' | sort)
    if [[ -n "$candidates" ]]; then
        echo "$candidates" | while read -r disk_name; do
            [[ -z "$disk_name" ]] && continue
            disk_is_system "$disk_name" || echo "$disk_name"
        done
        return
    fi

    # Fallback for non-draid machines: keep the original non-system disk behavior.
    fallback=$(lsblk -dn -o NAME,TYPE | awk '$2=="disk"{print $1}' | sort)
    echo "$fallback" | while read -r disk_name; do
        [[ -z "$disk_name" ]] && continue
        disk_is_system "$disk_name" || echo "$disk_name"
    done
}



result_handle_pre() {
    if [[ $disk_mode == SINGLE ]];then
        jobs_run=$(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | sed -n "/${str1}: (groupid=0/,/latency/p" | grep jobs | sed 's/.*\(jobs=.*\)):.*/\1/')
        readiops=$(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | sed -n "/${str1}: (groupid=0/,/latency/p" | grep "read:" | awk -F "IOPS=" '{print $2}' | awk -F "," '{print $1}')
        writeiops=$(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | sed -n "/${str1}: (groupid=0/,/latency/p" | grep "write:" | awk -F "IOPS=" '{print $2}' | awk -F "," '{print $1}')
        readbw_temp=$(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | sed -n "/${str1}: (groupid=0/,/latency/p" | grep "read:" | awk -F "BW=" '{print $2}' | awk -F "(" '{print $1}')
        writebw_temp=$(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | sed -n "/${str1}: (groupid=0/,/latency/p" | grep "write:" | awk -F "BW=" '{print $2}' | awk -F "(" '{print $1}')
        Lat=$(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | sed -n "/${str1}: (groupid=0/,/latency/p" | grep -i '[[:space:]]lat.*avg' | tail -n1 | awk -F "avg=" '{print $2}' | awk -F "," '{print $1}')
        CPUusr=$(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | sed -n "/${str1}: (groupid=0/,/latency/p" | grep cpu | awk -F "usr=" '{print $2}' | awk -F "," '{print $1}')
        CPUsys=$(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | sed -n "/${str1}: (groupid=0/,/latency/p" | grep cpu | awk -F "sys=" '{print $2}' | awk -F "," '{print $1}')
        sn=$(smartctl -i /dev/${str1} | grep -i 'serial number' | sed 's/.*:[[:blank:]]*\([0-9a-zA-Z]*\)/\1/')
    elif [[ $disk_mode == SUBALL ]];then

#        jobs_run=$(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | sed -n "/${str1}: (groupid=0/,/latency/p" | grep jobs | sed 's/.*\(jobs=.*\)):.*/\1/')
        iodepth=$(less "$Config_Dir/$configuration" | grep iodepth | awk -F "=" '{print $2}')
        rw_temp=$(less "$Config_Dir/$configuration" | sed -n 7p | awk -F "=" '{print $2}')
        read_percentage=$(less "$Config_Dir/$configuration" | grep rwmixread | awk -F "=" '{print $2}')
        size=$(less "$Config_Dir/$configuration" | grep bs | awk -F "=" '{print $2}' | head -n1)
        run_time=$(less "$Config_Dir/$configuration" | grep runtime | awk -F "=" '{print $2}')

        readiops_array=($(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | sed -n "/${str1}: (groupid=0/,/latency/p" | grep "read:" | awk -F "IOPS=" '{print $2}' | awk -F "," '{print $1}'))
        writeiops_array=($(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | sed -n "/${str1}: (groupid=0/,/latency/p" | grep "write:" | awk -F "IOPS=" '{print $2}' | awk -F "," '{print $1}'))
        if [[ $readiops_array =~ "k" || $writeiops_array =~ "k" ]];then
            readiops_array=($(echo ${readiops_array[*]} | sed 's/k/000/g'))
            writeiops_array=($(echo ${writeiops_array[*]} | sed 's/k/000/g'))
        fi
        readbw_array=($(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | sed -n "/${str1}: (groupid=0/,/latency/p" | grep "read:" | awk -F "BW=" '{print $2}' | awk -F "(" '{print $1}'))
        writebw_array=($(cat $Result_Dir/detresult/${loop}_${jobnum}.txt  | sed -n "/${str1}: (groupid=0/,/latency/p" | grep "write:" | awk -F "BW=" '{print $2}' | awk -F "(" '{print $1}'))
        Lat_array=($(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | sed -n "/${str1}: (groupid=0/,/latency/p" | grep -i '[[:space:]]lat.*avg' | awk -F "avg=" '{print $2}' | awk -F "," '{print $1}'))
        CPUusr_array=($(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | sed -n "/${str1}: (groupid=0/,/latency/p" | grep cpu | awk -F "usr=" '{print $2}' | awk -F "," '{print $1}'))
        CPUsys_array=($(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | sed -n "/${str1}: (groupid=0/,/latency/p" | grep cpu | awk -F "sys=" '{print $2}' | awk -F "," '{print $1}'))
        sn=$(smartctl -i /dev/${str1} | grep -i 'serial number' | sed 's/.*:[[:blank:]]*\([0-9a-zA-Z]*\)/\1/')

        NUMS=$(less $configuration | grep jobs | awk -F '=' '{print $2}')
        jobs_run=$NUMS
        OLD_IFS="$IFS"
        IFS=" "
        CPUusr_array=($(echo ${CPUusr_array[*]} | sed 's/%//g'))
        CPUsys_array=($(echo ${CPUsys_array[*]} | sed 's/%//g'))
        IFS="$OLD_IFS"
#        echo ${CPUsys_array[*]}"*******************"
#        echo ${CPUusr_array[*]}"*******************"
        Lat=0
        CPUusr=0
        CPUsys=0
        readbw=0
        writebw=0
        readiops=0
        writeiops=0

		for ((d=0; d<$NUMS; d++));do
		     if [[ -z ${readiops_array[${d}]} ]];then
                readiops_array[${d}]=0
            fi
             if [[ -z ${writeiops_array[${d}]} ]];then
                writeiops_array[${d}]=0
            fi
            if [[ -z  ${readbw_array[${d}]} ]]; then
                #readbw_temp=0
                readbw_array[${d}]=0
            else
                readbw_array[${d}]=$(div ${readbw_array[${d}]})
            fi
            if [[ -z  ${writebw_array[${d}]} ]]; then
                #readbw_temp=0
                writebw_array[${d}]=0
            else
                writebw_array[${d}]=$(div ${writebw_array[${d}]})
            fi
#            echo "xxxx${Lat_array[$d]}"
#            echo "xxxx${CPUusr_array[$d]}"
		    readiops=$(echo "$readiops + ${readiops_array[${d}]}" | bc 2>/dev/null)
		    writeiops=$(echo "$writeiops + ${writeiops_array[${d}]}" | bc 2>/dev/null)
		    Lat=$(echo "$Lat + ${Lat_array[${d}]}" | bc)
		    CPUusr=$(printf "%.2f" $(echo "scale=2;$CPUusr + ${CPUusr_array[$d]}" | bc))
		    CPUsys=$(printf "%.2f" $(echo "scale=2;$CPUsys + ${CPUsys_array[$d]}" | bc))
		    readbw_temp=$(echo ${readbw_array[${d}]} | sed 's/M//g' | sed 's/i//g' | sed 's/B//g' | sed 's/\///g' | sed 's/s//g')
		    writebw_temp=$(echo ${writebw_array[${d}]} | sed 's/M//g' | sed 's/i//g' | sed 's/B//g' | sed 's/\///g' | sed 's/s//g')
		    readbw=$(printf "%.2f" $(echo "scale=2;$readbw + $readbw_temp" | bc))
		    writebw=$(printf "%.2f" $(echo "scale=2;$writebw + $writebw_temp" | bc))
		done
#        readbw_temp=$readbw
#        writebw_temp=$writebw
        if [[ -z $readiops ]]; then
		    readiops=0
		fi
		if [[ -z $writeiops ]]; then
		    writeiops=0
		fi
		iops=$(echo "$readiops + $writeiops" | bc)
		bw=$(echo "$readbw + $writebw" | bc)
		if [[ ${readbw_array[0]} =~ "i" || ${writebw_array[0]} ]];then
		    bw=$(echo "$bw"MiB)
            readbw=$(echo $readbw)MiB
            writebw=$(echo $writebw)MiB
        else
            bw=$(echo "$bw"MB)
            readbw=$(echo $readbw)MB
            writebw=$(echo $writebw)MB
        fi

        if [ -z $read_percentage ]; then
            rw=$rw_temp
        else
            rw=$(echo "$rw_temp-$read_percentage")
        fi
        return 0


    elif [[ $disk_mode == ALL ]];then
#        result_dir="$Result_Dir/detresult/${loop}_${jobnum}.txt"
#        cmd="cat $result_dir"
        jobs_run=$(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | grep "jobs=" | sed 's/.*\(jobs=.*\)):.*/\1/')
        readiops=$(cat $Result_Dir/detresult/${loop}_${jobnum}.txt| grep "read:" | awk -F "IOPS=" '{print $2}' | awk -F "," '{print $1}')
        writeiops=$( cat $Result_Dir/detresult/${loop}_${jobnum}.txt | grep "write:" | awk -F "IOPS=" '{print $2}' | awk -F "," '{print $1}')
        readbw_temp=$(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | grep "read:" | awk -F "BW=" '{print $2}' | awk -F "(" '{print $1}')
        writebw_temp=$( cat $Result_Dir/detresult/${loop}_${jobnum}.txt | grep "write:" | awk -F "BW=" '{print $2}' | awk -F "(" '{print $1}')
        Lat=$( cat $Result_Dir/detresult/${loop}_${jobnum}.txt | grep -i '[[:space:]]lat.*avg' | tail -n1 | awk -F "avg=" '{print $2}' | awk -F "," '{print $1}')
        CPUusr=$(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | grep cpu | awk -F "usr=" '{print $2}' | awk -F "," '{print $1}')
        CPUsys=$(cat $Result_Dir/detresult/${loop}_${jobnum}.txt | grep cpu | awk -F "sys=" '{print $2}' | awk -F "," '{print $1}')
    fi

    iodepth=$(grep iodepth "$Config_Dir/$configuration" | awk -F "=" '{print $2}')
    rw_temp=$(sed -n 7p "$Config_Dir/$configuration" | awk -F "=" '{print $2}')
    read_percentage=$(grep rwmixread "$Config_Dir/$configuration" | awk -F "=" '{print $2}')
    size=$(grep bs "$Config_Dir/$configuration" | awk -F "=" '{print $2}' | head -n1)
    run_time=$(grep runtime "$Config_Dir/$configuration" | awk -F "=" '{print $2}')
    if [[ -z $readiops ]]; then
        readiops=0
    fi
    if [[ -z $writeiops ]]; then
        writeiops=0
    fi
    if [[ -z $readbw_temp ]]; then
        #readbw_temp=0
        readbw=0
    else
        readbw=$(div "$readbw_temp")
    fi
    if [[ -z $writebw_temp ]]; then
        #readbw_temp=0
        writebw=0
    else
        writebw=$(div "$writebw_temp")
    fi
    if [[ $readiops =~ "k" ]] || [[ $writeiops =~ "k" ]]; then
        readiops_temp=$(echo "$readiops" | sed 's/k//g')
        writeiops_temp=$(echo "$writeiops" | sed 's/k//g')
        iops=$(echo "$readiops_temp + $writeiops_temp" | bc)
        iops=$(echo "$iops"k)
    else
        readiops_temp=$(echo "$readiops")
        writeiops_temp=$(echo "$writeiops")
        iops=$(echo "$readiops_temp + $writeiops_temp" | bc)
        iops=$(echo "$iops")
    fi

    readbw_temp1=$(echo "$readbw" | sed 's/M//g' | sed 's/i//g' | sed 's/B//g' | sed 's/\///g' | sed 's/s//g')
    writebw_temp1=$(echo "$writebw" | sed 's/M//g' | sed 's/i//g' | sed 's/B//g' | sed 's/\///g' | sed 's/s//g')
    bw=$(echo "$readbw_temp1 + $writebw_temp1" | bc | awk '{printf "%.2f", $0}')
    bw=$(echo "$bw"MiB)
    if [ -z $read_percentage ]; then
        rw=$rw_temp
    else
        rw=$(echo "$rw_temp-$read_percentage")
    fi

}

result_handle_after() {

    echo "iodepth=$iodepth, transfer request size=$size, 100% $rw, runtime=$run_time, $jobs_run  " | tee -a $Result_Dir/result.log
    echo "ReadIOPs=$readiops" | tee -a $Result_Dir/result.log
    echo "WriteIOPs=$writeiops" | tee -a $Result_Dir/result.log
    echo "IOPs=$iops" | tee -a $Result_Dir/result.log
    echo "Readbw=$readbw" | tee -a $Result_Dir/result.log
    echo "Writebw=$writebw" | tee -a $Result_Dir/result.log
    echo "bw=$bw" | tee -a $Result_Dir/result.log
    echo "Lat(usec)=$Lat" | tee -a $Result_Dir/result.log
    echo "CPUusr=$CPUusr" | tee -a $Result_Dir/result.log
    echo "CPUsys=$CPUsys" | tee -a $Result_Dir/result.log
    echo -e "\n\n"

}






fio_idle_timeout_seconds()
{
    local idle_seconds="${FIO_IDLE_TIMEOUT_SECONDS:-}"
    local idle_minutes="${TEST_IDLE_TIMEOUT_MINUTES:-}"

    if echo "$idle_minutes" | grep -Eq '^[0-9]+$'; then
        echo $((idle_minutes * 60))
        return
    fi
    if ! echo "$idle_seconds" | grep -Eq '^[0-9]+$'; then
        idle_seconds=900
    fi
    echo "$idle_seconds"
}

fio_io_progress_signature()
{
    local configuration="${1:-}"
    [[ -f "$configuration" ]] || return 0
    awk -F= '
        /^[[:space:]]*filename[[:space:]]*=/ {
            value=$0
            sub(/^[^=]*=/, "", value)
            count=split(value, paths, ":")
            for (i=1; i<=count; i++) print paths[i]
        }
    ' "$configuration" 2>/dev/null | while read -r device_path; do
        local disk_name
        disk_name=$(basename "$device_path")
        [[ -z "$disk_name" ]] && continue
        assert_not_system_disk "$disk_name" "monitor fio IO" >/dev/null 2>&1 || continue
        stat_file="/sys/class/block/${disk_name}/stat"
        [[ -r "$stat_file" ]] || continue
        awk -v dev="$disk_name" '{ print dev ":" $3 ":" $7 }' "$stat_file"
    done | sort -u
}

# True if FIO output shows any positive IOPS (at least one disk/job did IO).
fio_output_has_successful_io()
{
    local output_file="$1"
    [[ -f "$output_file" ]] || return 1
    awk '
        BEGIN { found=0 }
        {
            line=$0
            while (match(line, /IOPS=[^ ,)]+/)) {
                val=substr(line, RSTART+5, RLENGTH-5)
                line=substr(line, RSTART+RLENGTH)
                gsub(/[kKmMgGtT]/, "", val)
                if (val+0 > 0) { found=1; exit }
            }
        }
        END { exit found ? 0 : 1 }
    ' "$output_file"
}



# Disk names mentioned in FIO error lines (io_u error on /dev/X, or job err= nonzero).
fio_error_disks()
{
    local output_file="$1"
    [[ -f "$output_file" ]] || return 0
    awk '
        {
            if (match($0, /\/dev\/[A-Za-z0-9._-]+/) && $0 ~ /io_u error|error on file/) {
                name=substr($0, RSTART+5, RLENGTH-5)
                print name
                next
            }
            if ($0 ~ /^[A-Za-z0-9._-]+:/ && $0 ~ /err= *[1-9]/) {
                split($1, parts, ":")
                if (parts[1] != "" && parts[1] != "fio") print parts[1]
            }
        }
    ' "$output_file" | sort -u
}

# Config name: N-mode-bs-qd-runtime.log -> human model label + planned runtime seconds.
fio_model_label()
{
    local configuration="$1"
    local base mode bs qd rt
    base=$(basename "${configuration}" .log)
    base=${base%% *}
    if [[ "$base" =~ ^([0-9]+)-([A-Za-z0-9_]+)-([A-Za-z0-9.]+)-([0-9]+)-([0-9]+)$ ]]; then
        mode="${BASH_REMATCH[2]}"
        bs="${BASH_REMATCH[3]}"
        qd="${BASH_REMATCH[4]}"
        rt="${BASH_REMATCH[5]}"
        printf '%s bs=%s qd=%s runtime=%ss (#%s)' "$mode" "$bs" "$qd" "$rt" "${BASH_REMATCH[1]}"
        return
    fi
    printf '%s' "$base"
}

fio_planned_runtime_seconds()
{
    local configuration="$1"
    local base
    base=$(basename "${configuration}" .log)
    base=${base%% *}
    if [[ "$base" =~ ^[0-9]+-[A-Za-z0-9_]+-[A-Za-z0-9.]+-[0-9]+-([0-9]+)$ ]]; then
        printf '%s' "${BASH_REMATCH[1]}"
        return
    fi
    printf 'unknown'
}

format_elapsed_hms()
{
    local total="$1"
    local hours minutes seconds
    if ! [[ "$total" =~ ^[0-9]+$ ]]; then
        printf '%s' "$total"
        return
    fi
    hours=$((total / 3600))
    minutes=$(((total % 3600) / 60))
    seconds=$((total % 60))
    if [[ "$hours" -gt 0 ]]; then
        printf '%dh%02dm%02ds' "$hours" "$minutes" "$seconds"
    elif [[ "$minutes" -gt 0 ]]; then
        printf '%dm%02ds' "$minutes" "$seconds"
    else
        printf '%ds' "$seconds"
    fi
}

run_fio_with_watchdog()
{
    local configuration="$1"
    local output_file="$2"
    local idle_timeout_seconds
    # Poll for FIO exit every 1s. A 30s sleep here used to add a second full
    # interval after runtime=30s jobs, so mix jobs reported elapsed~61s.
    local watch_interval_seconds="${FIO_WATCH_INTERVAL_SECONDS:-1}"
    local io_check_interval_seconds="${FIO_IO_CHECK_INTERVAL_SECONDS:-30}"
    local fio_pid
    local fio_rc
    local last_progress_ts
    local last_io_check_ts
    local last_output_size
    local last_io_signature
    local current_output_size
    local current_io_signature
    local now_ts
    local idle_timed_out=0
    local start_ts end_ts elapsed
    local model_label planned_runtime elapsed_hms config_name
    # Reset per-invocation so each FIO job can fire once on first EIO.
    FIO_EIO_BUNDLE_TRIGGERED=0
    shift 2

    idle_timeout_seconds=$(fio_idle_timeout_seconds)
    start_ts=$(date +%s)
    model_label=$(fio_model_label "$configuration")
    planned_runtime=$(fio_planned_runtime_seconds "$configuration")
    config_name=$(basename "$configuration")
    echo "$(date '+%F %T') [FIO] start model=${model_label} config=${config_name} planned_runtime=${planned_runtime}s idle_watchdog=${idle_timeout_seconds}s" | tee -a "$output_file"
    setsid bash -c 'fio "$@"' fio_runner "$configuration" "$@" >> "$output_file" 2>&1 &
    fio_pid=$!
    last_progress_ts=$start_ts
    last_io_check_ts=$start_ts
    last_output_size=$(wc -c < "$output_file" 2>/dev/null || echo 0)
    last_io_signature=$(fio_io_progress_signature "$configuration" | sha256sum | awk '{print $1}')

    while kill -0 "$fio_pid" 2>/dev/null; do
        sleep "$watch_interval_seconds"
        if ! kill -0 "$fio_pid" 2>/dev/null; then
            break
        fi
        now_ts=$(date +%s)
        current_output_size=$(wc -c < "$output_file" 2>/dev/null || echo 0)
        if [[ "$current_output_size" != "$last_output_size" ]]; then
            last_progress_ts=$now_ts
            last_output_size=$current_output_size
            # While FIO is still alive: if log already shows EIO, collect immediately.
            if [[ "${FIO_EIO_BUNDLE_TRIGGERED}" != "1" ]] && fio_log_has_eio "$output_file"; then
                echo "$(date '+%F %T') [FIO] EIO detected while fio still running (pid=${fio_pid}); collecting live failure bundle" \
                    | tee -a "$output_file" "$Result_Dir/result.log"
                trigger_live_failure_bundle "fio_eio_live:${config_name}"
                # Do not let collect/gcore duration look like FIO idle.
                last_progress_ts=$(date +%s)
            fi
        fi
        if [[ $((now_ts - last_io_check_ts)) -ge $io_check_interval_seconds ]]; then
            last_io_check_ts=$now_ts
            current_io_signature=$(fio_io_progress_signature "$configuration" | sha256sum | awk '{print $1}')
            if [[ -n "$current_io_signature" && "$current_io_signature" != "$last_io_signature" ]]; then
                last_progress_ts=$now_ts
                last_io_signature=$current_io_signature
            fi
            # Periodic EIO scan even if output size is steady (rare for fio error lines).
            if [[ "${FIO_EIO_BUNDLE_TRIGGERED}" != "1" ]] && fio_log_has_eio "$output_file"; then
                echo "$(date '+%F %T') [FIO] EIO detected (periodic scan) while fio pid=${fio_pid}; collecting live failure bundle" \
                    | tee -a "$output_file" "$Result_Dir/result.log"
                trigger_live_failure_bundle "fio_eio_live:${config_name}"
                last_progress_ts=$(date +%s)
            fi
        fi
        if [[ $((now_ts - last_progress_ts)) -ge $idle_timeout_seconds ]]; then
            idle_timed_out=1
            elapsed=$((now_ts - start_ts))
            elapsed_hms=$(format_elapsed_hms "$elapsed")
            echo "$(date '+%F %T') [FIO] idle watchdog timeout after ${idle_timeout_seconds}s without output or non-system disk IO progress, model=${model_label}, config=${config_name}, elapsed=${elapsed}s(${elapsed_hms}), planned_runtime=${planned_runtime}s" | tee -a "$output_file" "$Result_Dir/result.log"
            kill -TERM "-${fio_pid}" 2>/dev/null || kill -TERM "$fio_pid" 2>/dev/null || true
            sleep 5
            kill -KILL "-${fio_pid}" 2>/dev/null || kill -KILL "$fio_pid" 2>/dev/null || true
            break
        fi
    done

    if [[ "$idle_timed_out" == "1" ]]; then
        wait "$fio_pid" 2>/dev/null || true
        fio_rc=124
    else
        wait "$fio_pid"
        fio_rc=$?
    fi
    end_ts=$(date +%s)
    elapsed=$((end_ts - start_ts))
    elapsed_hms=$(format_elapsed_hms "$elapsed")
    FIO_LAST_MODEL="$model_label"
    FIO_LAST_CONFIG="$config_name"
    FIO_LAST_ELAPSED_SECONDS="$elapsed"
    FIO_LAST_PLANNED_RUNTIME="$planned_runtime"
    FIO_LAST_RC="$fio_rc"
    echo "$(date '+%F %T') [FIO] finish model=${model_label} config=${config_name} rc=${fio_rc} elapsed=${elapsed}s(${elapsed_hms}) planned_runtime=${planned_runtime}s" | tee -a "$output_file"
    if [[ $fio_rc -eq 124 ]]; then
        echo "FIO command failed, model=${model_label}, config=${config_name}, elapsed=${elapsed}s(${elapsed_hms}), planned_runtime=${planned_runtime}s, rc=${fio_rc}" | tee -a "$output_file" "$Result_Dir/result.log"
        append_fio_error_detail "$output_file" "$model_label" "$fio_rc"
        if fio_log_has_eio "$output_file"; then
            trigger_live_failure_bundle "fio_eio_exit:${config_name}"
        fi
        return "$fio_rc"
    fi
    if [[ $fio_rc -ne 0 ]]; then
        # Any FIO/disk IO error fails the stage immediately.
        echo "FIO command failed, model=${model_label}, config=${config_name}, elapsed=${elapsed}s(${elapsed_hms}), planned_runtime=${planned_runtime}s, rc=${fio_rc}" | tee -a "$output_file" "$Result_Dir/result.log"
        append_fio_error_detail "$output_file" "$model_label" "$fio_rc"
        # If EIO and we missed the live window, collect ASAP after exit.
        if fio_log_has_eio "$output_file"; then
            trigger_live_failure_bundle "fio_eio_exit:${config_name}"
        fi
    fi
    return $fio_rc
}

# Extract concrete fio error lines from a job log and tee them to console + result.log.
append_fio_error_detail()
{
    local log_file="$1"
    local model_label="${2:-unknown}"
    local fio_rc="${3:-?}"
    local log_name
    local matched=""
    local line_count=0

    log_name=$(basename "${log_file:-unknown.log}")
    {
        echo "----- FIO error detail begin (log=${log_name} model=${model_label} rc=${fio_rc}) -----"
        if [[ -n "$log_file" && -f "$log_file" ]]; then
            matched=$(
                grep -E \
                    'fio:|io_u error|err=|error=|Invalid argument|I/O error|Input/output error|No such device|direct IO errored|failed to|errno=' \
                    "$log_file" 2>/dev/null | tail -n 60 || true
            )
            if [[ -n "$matched" ]]; then
                printf '%s\n' "$matched"
                line_count=$(printf '%s\n' "$matched" | wc -l | tr -d ' ')
            else
                echo "(no fio error keywords matched; last 40 lines of ${log_name}:)"
                tail -n 40 "$log_file" 2>/dev/null || true
                line_count=40
            fi
        else
            echo "(fio log missing: ${log_file:-})"
        fi
        echo "----- FIO error detail end (lines=${line_count}) -----"
    } | tee -a "${log_file:-/dev/null}" "$Result_Dir/result.log"
}





function run_all()
{
    cd $Config_Dir
    echo "**********" `date +%m-%d" "%H:%M:%S` "Running FIO As All Mode,Reports For ALL Disk  **********"
    num=`cat $Cur_Dir/$filename |grep -v -i 'End'|wc -l`
    totalnum=`expr $num - 1`
    jobnum=1
    printf "%-10s %-12s %-10s %-12s %-10s %-10s %-8s %-18s %-18s %-12s %-11s %-10s %-10s\n" Test-Mode, Queue-Depth, Blocksize, NumJbs, ReadIOPS, WriteIOPS, IOPS, Read_Bandwidth, Write_Bandwindth, Bandwidth, Latency, CPUusr%, CPUsys% >>$Result_Dir/result_$loop.csv
    rm -rf stor*
    for configuration in `ls -p $Config_Dir | grep -v / | grep '\.log$' | sort -n -k 1 -t -`
    do
        echo `date +%m-%d" "%H:%M:%S` >>$Result_Dir/detresult/"${loop}_$jobnum.txt"
        echo "Job $jobnum/$totalnum is Running.."
        run_fio_with_watchdog "$configuration" "$Result_Dir/detresult/${loop}_$jobnum.txt" --write_bw_log=$LogAd/test-fio --write_iops_log=$LogAd/test-fio
        local fio_rc=$?
        if [[ $fio_rc -ne 0 ]]; then
            echo "FIO stage abort, model=${FIO_LAST_MODEL:-unknown}, config=${FIO_LAST_CONFIG:-$(basename "$configuration")}, elapsed=${FIO_LAST_ELAPSED_SECONDS:-?}s, planned_runtime=${FIO_LAST_PLANNED_RUNTIME:-?}s, rc=${fio_rc}" | tee -a $Result_Dir/result.log
            return $fio_rc
        fi
        result_handle_pre
        printf "%-10s %-12s %-10s %-12s %-10s %-10s %-8s %-18s %-18s %-12s %-11s %-10s %-10s\n" $rw, $iodepth, $size, $jobs_run, $readiops, $writeiops, $iops, $readbw, $writebw, $bw, $Lat, $CPUusr, $CPUsys >>$Result_Dir/result_$loop.csv
        echo "**********" $(date +%m-%d" "%H:%M:%S) "Running FIO As All Disk**********" >>$Result_Dir/result.log
        result_handle_after
        jobnum=`echo "$jobnum + 1" | bc -l`
    done
    cd $Job_Dir
}



function calculate()
{
    percen_flag="false"
    b_v=$1
	c_v=$2
	if echo "$1" | grep -E '^\.' >& /dev/null; then
        	c_v=0"$c_v"
        	b_v=0"$b_v"
	fi
	if echo "$1"|grep -E 'MiB$' >& /dev/null; then
        	c_v=`echo "$c_v" | sed 's/..$//'`
        	b_v=`echo "$b_v" | sed 's/..$//'`
	fi
	if echo "$1" | grep -E '%$' >& /dev/null; then
        	c_v=`echo "$2" | sed 's/.$//'`
        	b_v=`echo "$1" | sed 's/.$//'`
	fi
        difference=`echo "scale=2;$b_v-$c_v" | bc -l | cut -c1`
	if [ "$difference" != "0" ]; then
        	difference=`echo "scale=2;$b_v-$c_v" | bc -l`
	        rs=`echo "scale=0;($difference-0)>0" | bc -l`
	       	[[ $rs -eq 0 ]] && difference=`echo "scale=2;0-($difference)" | bc -l`
	        percen_diff=$(echo "scale=2;($difference/$c_v)*100" |bc -l)
	        rs=`echo "($percen_diff-$diff)>0" | bc -l`
        	[[ $rs -ne 0 ]] && percen_flag="true"
	fi
}

function comparebw()
{
	local i
	local j
	local k
	local l
	local m
	if [[ -z "$beforeloop" || -z "$loop" ]]; then
        return 0
    fi
	before_total_result=$Result_Dir/result_"$beforeloop".csv
	current_total_result=$Result_Dir/result_"$loop".csv

    if [[ ! -f "$before_total_result" || ! -f "$current_total_result" ]]; then
        return 0
    fi

	cmp_lines=`cat "$before_total_result" | wc -l`
	title=`head -n 1 "$current_total_result"`
	title_item=`echo "$title" | awk -F',' '{print NF}'`
	let title_item=title_item-6
	echo "Total data compare that result_x.cvs content compare" >$Cur_Dir/error.log
	for((i=2;i<=$cmp_lines;i++))
	do
		Test_Mode=`echo "$title" | awk -F',' '{print $1}'`
		Queue_Depth=`echo "$title" | awk -F',' '{print $2}'`
		Block_Size=`echo "$title" | awk -F',' '{print $3}'`
		for((j=4;j<=$title_item;j++))
		do
			compare_item=`echo "$title" |  awk -F',' -v var=$j 'NR==1 {for(n=1;n<=NF;n++) if(n==var) print $n}'`
			compare_value_b=`sed -n "$i"p  $before_total_result |  awk -F',' -v var=$j 'NR==1 {for(n=1;n<=NF;n++) if(n==var) print $n}'`
			compare_value_c=`sed -n "$i"p  $current_total_result |  awk -F',' -v var=$j 'NR==1 {for(n=1;n<=NF;n++) if(n==var) print $n}'`

			calculate $compare_value_b $compare_value_c
			if [ $percen_flag == "true" ]; then
                echo "Between $beforeloop loop and $loop loop compare item: $compare_item occur great difference greater than $diff%" | tee -a $Cur_Dir/error.log
                echo "compare item: $compare_item $beforeloop loop $compare_value_b $loop loop $compare_value_c" | tee -a $Cur_Dir/error.log
                error_flag="true"
            fi
		done
	done
	echo "Total data compare that sdx_x.cvs content compare" >>$Cur_Dir/error.log
	cmp_disks=($(find $Result_Dir/* | grep -E 'sd[a-z]'|awk -F'/' '{print $NF}' | awk -F'_' '{print $1}'|uniq))
	echo "Toatal the compare Disk: ${cmp_disks[@]}"
	for k in ${cmp_disks[@]}
	do
		echo "The compare Disk: $k"
		cmp_lines=`cat $Result_Dir/"$k"_"$loop".csv | wc -l`
		title=`head -n 1 $Result_Dir/"$k"_"$loop".csv`
		title_item=`echo "$title" | awk -F',' '{print NF}'`
		for((l=2;l<=$cmp_lines;l++))
		do
			disk=`echo "$title" | awk -F',' '{print $1}'`
			test_mode=`echo "$title" | awk -F',' '{print $2}'`
			q_d=`echo "$title" | awk -F',' '{print $3}'`
			block_size=`echo "$title" | awk -F',' '{print $4}'`
			for((m=5;m<=$title_item;m++))
			do
				compare_item=`echo "$title" |  awk -F',' -v var=$m '{for(n=1;n<=NF;n++) if(n==var) print $n}'`
				compare_value_b=`sed -n "$l"p  $Result_Dir/"$k"_"$beforeloop".csv |  awk -F',' -v var=$m '{for(n=1;n<=NF;n++) if(n==var) print $n}'`
				compare_value_c=`sed -n "$l"p  $Result_Dir/"$k"_"$loop".csv |  awk -F',' -v var=$m '{for(n=1;n<=NF;n++) if(n==var) print $n}'`

				calculate $compare_value_b $compare_value_c
				if [ $percen_flag == "true" ]; then
 	        	                echo "Between $beforeloop loop and $loop loop $k compare item: $compare_item occur great difference greater than $diff%" | tee -a $Cur_Dir/error.log
                        	        echo "$k compare item: $compare_item $beforeloop loop $compare_value_b $loop loop $compare_value_c" | tee -a $Cur_Dir/error.log
                                	error_flag="true"
                        	fi
			done
		done
	done
}

#####################################
##The below function use to check phyerr and crc error after run fio##







########Modify by wuwei for multithreads and random-configuration

all()
{
    rm -rf $Result_Dir/*.log $Result_Dir/*.html $Result_Dir/.fio*
    jobnum=1
    for b in $config_list
    do
        rm -rf $Job_Dir/*.log >/dev/null
        echo "(LOOP-Diskmode)$loop - all" >>$Result_Dir/result.log
        echo "Run $b" >>$Result_Dir/result.log
        echo "" >> $File_Dir/$b
        echo "End" >> $File_Dir/$b
        configure
        run_all $b || return $?
    done
    if [[ -n "$loop" ]] && [ "$loop" -gt 1 ] && ! powercycle_mode_enabled; then
        comparebw
        if [ "$error_flag" = "true" ]; then
            echo "FIO + DC test fail occur great difference between $beforeloop and $loop,more detail message to see $result/error.log"
        fi
    fi
}


function get_config_filelist() {
    rm -rf $File_Dir/*
    if [[ -z "$filename" ]]; then
        echo "PowerCycle FIO requires filename=powercycle_auto.csv (prepare_powercycle_plan)."
        return 1
    fi
    cp -r $Cur_Dir/$filename $File_Dir/ >/dev/null
    if ! grep -q "End" $File_Dir/$filename; then
        echo "End" >> $File_Dir/$filename
    fi
    rm -rf $Cur_Dir/config_list1.log
    ls -p $File_Dir | grep -v / | grep "\.csv" | awk '{print $NF}' > $Cur_Dir/config_list.log
    while read i
    do
        echo "$i $RANDOM"
    done<$Cur_Dir/config_list.log|sort -k2n|cut -d " " -f1>$Cur_Dir/config_list1.log
    config_list=`cat $Cur_Dir/config_list1.log`
    rm -rf $Cur_Dir/config_list.log >/dev/null
}





function run_mode() {
    if [ "$disk_mode" != "ALL" ]; then
        echo "PowerCycle only supports disk_mode=ALL, got $disk_mode"
        return 1
    fi
    all || return $?
    return 0
}

function do_fio() {
        local power_log="$ResultLog/reboot_command.log"
        if [ "$item" = "DC" ]; then
            power_log="$ResultLog/dc_command.log"
        fi

        get_system_disk
        # 安全护栏：无法识别系统盘时直接中止，避免误把系统盘当作数据盘
        if [[ -z "$system_disk" ]];then
            echo -ne " Fail to detect system disk. Refuse to run to avoid any IO on OS disk. Exit.\n"
            echo "$(date '+%F %T') [FIO] failed: system disk not detected, sources=${system_disk_sources:-EMPTY}" | tee -a "$power_log"
            exit 1
        fi
        if [[ "$specified_disk" =~ "null" ]];then
            # 仅选取 TYPE=disk 的真实块设备，排除 loop/rom 等虚拟设备；
            # 再用 -w 精确匹配整词剔除系统盘，确保绝不对系统盘或虚拟设备做 IO
            disk=$(select_auto_test_disks)
            OLD_IFS="$IFS"
            IFS=" "
            disk=($disk)
            IFS="$OLD_IFS"
            test_disk=`echo ${disk[@]}|sed 's/ /,/g'`
        elif specified_disk_contains_system; then
            # 指定磁盘中包含系统盘：为保证不对系统盘做 IO，直接中止
            echo "Specified disk contains system disk [$system_disk]. Refuse to run to avoid IO on OS disk. Exit."
            exit 1
        else
            disk=$(echo ${specified_disk} | sed 's/,/ /g')
            OLD_IFS="$IFS"
            IFS=" "
            disk=($disk)
            IFS="$OLD_IFS"
            test_disk=$specified_disk
        fi

        validate_test_disks || return $?
        echo -ne "System_Disk is $system_disk\n"
        echo -ne "The test disk is: $test_disk\n"
        echo "$(date '+%F %T') [FIO] system_disk=$system_disk test_disk=${test_disk:-EMPTY} specified_disk=$specified_disk disk_mode=$disk_mode" | tee -a "$power_log"
        if [[ -z "$test_disk" ]]; then
            echo "No non-system test disk found. Set FIO_DISKS to the target data disk, for example sdb or nvme1n1." | tee -a "$power_log"
            return 1
        fi

        if powercycle_mode_enabled; then
            prepare_powercycle_plan
            plan_rc=$?
            echo "$(date '+%F %T') [FIO] prepare_powercycle_plan rc=$plan_rc filename=$filename" | tee -a "$power_log"
            [[ $plan_rc -ne 0 ]] && return $plan_rc
        fi

        get_config_filelist || return $?
        echo "$(date '+%F %T') [FIO] config_list=$(cat "$Cur_Dir/config_list1.log" 2>/dev/null | tr '\n' ' ')" | tee -a "$power_log"
        set_Disk
        set_disk_rc=$?
        echo "$(date '+%F %T') [FIO] set_Disk rc=$set_disk_rc" | tee -a "$power_log"
        [[ $set_disk_rc -ne 0 ]] && return $set_disk_rc
        run_mode
        run_rc=$?
        echo "$(date '+%F %T') [FIO] run_mode rc=$run_rc" | tee -a "$power_log"
        [[ $run_rc -ne 0 ]] && return $run_rc
        if powercycle_mode_enabled; then
            commit_powercycle_state
            echo "$(date '+%F %T') [FIO] committed powercycle state" | tee -a "$power_log"
        fi
        rm -rf $Cur_Dir/configuration.tmp*
        close_mount
        return 0
}




