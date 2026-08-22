#!/bin/bash
[[ -n "${_FIO_POWERCYCLE_LOADED:-}" ]] && return 0
_FIO_POWERCYCLE_LOADED=1

POWERCYCLE_PLAN_FILE="powercycle_auto.csv"
POWERCYCLE_STATE_FILE="$ResultLog/powercycle_state.json"
POWERCYCLE_STATE_NEXT_FILE="$ResultLog/powercycle_state.next.json"

function powercycle_mode_enabled() {
    [[ "$item" == "DC" || "$item" == "REBOOT" ]]
}

function get_min_test_disk_size_bytes() {
    local min_size=""
    local old_ifs="$IFS"
    IFS=" "
    local disks=($(echo "${test_disk}" | sed 's/,/ /g'))
    IFS="$old_ifs"

    for disk_name in "${disks[@]}"; do
        [[ -z "$disk_name" ]] && continue
        local disk_size
        disk_size=$(blockdev --getsize64 "/dev/${disk_name}" 2>/dev/null)
        [[ -z "$disk_size" ]] && continue
        if [[ -z "$min_size" || "$disk_size" -lt "$min_size" ]]; then
            min_size="$disk_size"
        fi
    done

    echo "$min_size"
}

function prepare_powercycle_plan() {
    local power_log="$ResultLog/reboot_command.log"
    if [ "$item" = "DC" ]; then
        power_log="$ResultLog/dc_command.log"
    fi
    local min_disk_size
    min_disk_size=$(get_min_test_disk_size_bytes)
    if [[ -z "$min_disk_size" ]]; then
        echo "Failed to detect test disk size for powercycle plan." | tee -a "$Result_Dir/result.log" "$power_log"
        return 1
    fi
    echo "$(date '+%F %T') [PLAN] min_disk_size_bytes=$min_disk_size" | tee -a "$power_log"

    rm -f "$Cur_Dir/$POWERCYCLE_PLAN_FILE" "$POWERCYCLE_STATE_NEXT_FILE"

    python3 "$Cur_Dir/powercycle_random.py" plan \
        --state "$POWERCYCLE_STATE_FILE" \
        --staged-state "$POWERCYCLE_STATE_NEXT_FILE" \
        --csv "$Cur_Dir/$POWERCYCLE_PLAN_FILE" \
        --current-loop "$loop" \
        --total-loops "$LOOP" \
        --min-disk-size-bytes "$min_disk_size" 2>&1 | tee -a "$Result_Dir/result.log" "$power_log"
    if [[ ${PIPESTATUS[0]} -ne 0 ]]; then
        echo "Failed to generate random powercycle plan." | tee -a "$Result_Dir/result.log" "$power_log"
        return 1
    fi

    filename="$POWERCYCLE_PLAN_FILE"
    echo "Use generated powercycle plan file: $filename" | tee -a "$Result_Dir/result.log" "$power_log"
    return 0
}

function commit_powercycle_state() {
    if [[ -f "$POWERCYCLE_STATE_NEXT_FILE" ]]; then
        mv -f "$POWERCYCLE_STATE_NEXT_FILE" "$POWERCYCLE_STATE_FILE"
    fi
}
count_time()
{
    loop=`sed -n '$p' $ResultLog/reboot.log|awk {'print $1'}`
    if [ -z $loop ];then
           loop=0
    fi
    Second=`date +%s`
    Second_pre=`sed -n '$p' $ResultLog/reboot.log|awk {'print $2'}`
    Second_count=`echo "$Second - $Second_pre" | bc`
    #let Second_count=expr $Second-$Second_pre
    if [ "$loop" = 0 ];then
	Second_count=0
    fi
    #awk 'BEGIN{getline a}{print a;a=$0}END{$0=gensub(/$/,"'$Second_count'",1,$0);print}' $ResultLog/reboot.log >$ResultLog/reboot1.log
    sed -r "$ s/$/\t$Second_count/" $ResultLog/reboot.log >$ResultLog/reboot1.log
    sleep 2
    mv $ResultLog/reboot1.log $ResultLog/reboot.log
	#overtime
}

overtime()
{
	overtime_temp=`sed -n '$p' $ResultLog/reboot.log|awk '{print $3}'`
    if [ $overtime_temp -gt 0 ] 2>/dev/null;then
		sed '1d' $ResultLog/reboot.log > $LogAd/tmp1
		local SECOND=`awk '{print $3}' $LogAd/tmp1`
		Second_min=`sed -n '1p' $LogAd/tmp1 | awk '{print $3}'`
		Second_max=`sed -n '1p' $LogAd/tmp1 | awk '{print $3}'`
		for Second_next in $SECOND
		do
			if [ "$Second_min" -gt "$Second_next" ];then
				Second_min=$Second_next
			elif [ "$Second_max" -lt "$Second_next" ];then
				 Second_max=$Second_next
			fi
		done
		overslow=`expr $Second_min \* 4`
		if [ "$Second_max" -gt "$overslow" ];then
			Loop_temp=`grep "$Second_max" $LogAd/tmp1 | awk '{print $1}'`
			Second_temp=`grep "$Second_max" $LogAd/tmp1 | awk '{print $3}'`
			echo "`date`:Overtime error Loop $Loop_temp used $Second_temp Seconds" >> $LogAd/error.out
		fi
		rm -rf $LogAd/tmp1
	fi
}
update_dmesg_summary()
{
    mkdir -p "$SystemLog" >/dev/null 2>&1 || true
    local summary="$SystemLog/dmesg_summary.log"
    local tmp
    tmp=$(mktemp "${SystemLog}/dmesg_summary.XXXXXX") || return 0
    local stamp
    stamp=$(date '+%F %T')
    {
        echo "################################################################################"
        echo "# Powercycle dmesg summary"
        echo "# item=${item:-unknown} planned_loops=${LOOP:-?} updated_at=${stamp}"
        echo "# Per-loop files: ${SystemLog}/dmesg_loop_<N>.log"
        echo "################################################################################"
    } > "$tmp"

    local -a ids=()
    local f base id
    for f in "$SystemLog"/dmesg_loop_*.log; do
        [[ -e "$f" ]] || continue
        base=$(basename "$f")
        id=${base#dmesg_loop_}
        id=${id%.log}
        case "$id" in
            ''|*[!0-9]*) continue ;;
        esac
        ids+=("$id")
    done

    if ((${#ids[@]})); then
        local sorted
        sorted=$(printf '%s\n' "${ids[@]}" | sort -n)
        while IFS= read -r id; do
            [[ -n "$id" ]] || continue
            f="$SystemLog/dmesg_loop_${id}.log"
            {
                echo
                echo "########## LOOP ${id} ##########"
                cat "$f"
                echo "########## END LOOP ${id} ##########"
            } >> "$tmp"
        done <<< "$sorted"
    else
        echo "# (no per-loop dmesg files yet)" >> "$tmp"
    fi

    mv -f "$tmp" "$summary"
}

# Capture reboot/dc dmesg for the current loop and refresh the summary file.
# loop 0 = initial boot before the first power-cycle; loop N = after the N-th cycle.
collect_powercycle_dmesg()
{
    if [[ "$item" != "REBOOT" && "$item" != "DC" ]]; then
        return 0
    fi

    mkdir -p "$SystemLog" >/dev/null 2>&1 || true
    local loop_id="${loop:-0}"
    case "$loop_id" in
        ''|*[!0-9]*) loop_id=0 ;;
    esac

    local out="$SystemLog/dmesg_loop_${loop_id}.log"
    local stamp
    stamp=$(date '+%F %T')
    local power_log="$ResultLog/reboot_command.log"
    if [[ "$item" == "DC" ]]; then
        power_log="$ResultLog/dc_command.log"
    fi

    {
        echo "===== dmesg loop ${loop_id} ====="
        echo "item=${item} LOOP=${LOOP:-?} collected_at=${stamp}"
        echo "host=$(hostname 2>/dev/null || true)"
        echo "================================"
        timeout 30 dmesg -T 2>/dev/null || timeout 30 dmesg 2>/dev/null || true
    } > "$out"

    update_dmesg_summary
    echo "$(date '+%F %T') [DMESG] saved loop=${loop_id} file=${out} summary=${SystemLog}/dmesg_summary.log" | tee -a "$power_log"
}

bmc_reset()
{
    if [ "$bmc_reset" = "YES" ];then
        service ipmi start >/dev/null
        if [[ $? -eq 0 ]];then
            ipmitool -I open mc reset cold
        else
            echo "The ipmi service can't start, and don't restart bmc"
        fi
    else
        echo "Do not reset bmc."
    fi
}

dc_utc()
{
    timedatectl set-timezone UTC
	echo 0 > /sys/class/rtc/rtc0/wakealarm
    Alarmtime=`date +%s`
    Alarmtime=`expr $Alarmtime + ${wait}`
    echo $Alarmtime > /sys/class/rtc/rtc0/wakealarm
    # Use hwclock if available, fallback to timedatectl, but don't block
    timeout 10 hwclock -w 2>/dev/null || timeout 10 timedatectl set-local-rtc 0 >> /dev/null 2>&1 || true
    echo "Now is `date +%s`"
    echo "Alarm is $Alarmtime"
    cat /proc/driver/rtc
    sleep 5
    echo "$(date '+%F %T') [DC] request start, mode=UTC, user=$(id -un), uid=$(id -u)" | tee -a "$ResultLog/dc_command.log"
    sleep ${POWER_CYCLE_COMMAND_GRACE:-15}
    poweroff
}

dc_rtc()
{
    Shutdown_Hour_temp=`expr ${wait} / 3600`
    let Shutdown_yu=${wait}%3600
    Shutdown_Min_temp=`expr $Shutdown_yu / 60`
    let Shutdown_Sec_temp=$Shutdown_yu%60
    let Shutdown_Hour=23-$Shutdown_Hour_temp
    let Shutdown_Min=59-$Shutdown_Min_temp
    let Shutdown_Sec=59-$Shutdown_Sec_temp
    date -s $Shutdown_Hour:$Shutdown_Min:$Shutdown_Sec
    # Sync system clock to hardware RTC before DC, but don't fail if hwclock is missing
    hwclock -w 2>/dev/null || timedatectl set-local-rtc 0 >> /dev/null 2>&1 || true
    echo "$(date '+%F %T') [DC] request start, mode=RTC, user=$(id -un), uid=$(id -u)" | tee -a "$ResultLog/dc_command.log"
    sleep ${POWER_CYCLE_COMMAND_GRACE:-15}
    poweroff
}


do_dc()
{
    dc_utc
}

function request_system_reboot()
{
    local reboot_cmd_log="$ResultLog/reboot_command.log"
    local rc=1

    echo "$(date '+%F %T') [REBOOT] request start, user=$(id -un), uid=$(id -u)" | tee -a "$reboot_cmd_log"
    sleep ${POWER_CYCLE_COMMAND_GRACE:-15}

    if [ "$(id -u)" -eq 0 ]; then
        systemctl reboot -i >>"$reboot_cmd_log" 2>&1 || reboot >>"$reboot_cmd_log" 2>&1 || shutdown -r now >>"$reboot_cmd_log" 2>&1
        rc=$?
    else
        sudo -n systemctl reboot -i >>"$reboot_cmd_log" 2>&1 || sudo -n reboot >>"$reboot_cmd_log" 2>&1 || sudo -n shutdown -r now >>"$reboot_cmd_log" 2>&1
        rc=$?
    fi

    echo "$(date '+%F %T') [REBOOT] command returned rc=$rc" | tee -a "$reboot_cmd_log"
    return $rc
}

function do_reboot()
{
    local command_log="$ResultLog/reboot_command.log"
    if [ "$item" = "DC" ]; then
        command_log="$ResultLog/dc_command.log"
    fi

    case "$loop" in
        ''|*[!0-9]*)
            echo "$(date '+%F %T') [POWER] invalid loop='$loop', reset to 0" | tee -a "$command_log"
            loop=0
            ;;
    esac
    case "$LOOP" in
        ''|*[!0-9]*)
            echo "$(date '+%F %T') [POWER] invalid LOOP='$LOOP', reset to 1" | tee -a "$command_log"
            LOOP=1
            ;;
    esac

    echo "$(date '+%F %T') [POWER] enter do_reboot item=$item loop=$loop LOOP=$LOOP force=${POWER_CYCLE_FORCE_ONCE:-0}" | tee -a "$command_log"

    if [ "$POWER_CYCLE_FORCE_ONCE" = "1" ] && [ "$loop" -ge "$LOOP" ]; then
        echo "$(date '+%F %T') [POWER] force one power-cycle for initial Jenkins trigger" | tee -a "$command_log"
        loop=0
        LOOP=1
    fi

    if [ "$loop" -ge "$LOOP" ]; then
        echo "$(date '+%F %T') [POWER] all power-cycle loops completed, no remaining reboot/dc command" | tee -a "$command_log"
        return 2
    fi

    let beforeloop=$loop
    let loop=$loop+1
    echo "Current loop is $loop"
    echo $loop $Second >> $ResultLog/reboot.log
    sleep 2
    echo "The system will delay in $delay second"
    sleep 1
    echo "Press Ctrl+c to stop running"
    sleep $delay

    if [ "$item" = "REBOOT" ];then
        autoopen
        sync
        request_system_reboot || exit $?
        sleep 60
        exit
    elif [ "$item" = "DC" ];then
        autoopen
        sync
        if [ "$mode" = "UTC" ];then
            dc_utc
            sleep 60
            exit
        elif [ "$mode" = "RTC" ];then
            dc_rtc
            sleep 60
            exit
        else
            echo "unsupport mode, exit"
            exit
        fi
    else
        echo "$item Test Complete once"
    fi

#    echo "FIO + DC test has been run $LOOP,it will be exit,if you want to run more times please modify the var loops"


}
