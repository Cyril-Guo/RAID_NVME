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
    local min_disk_size
    min_disk_size=$(get_min_test_disk_size_bytes)
    if [[ -z "$min_disk_size" ]]; then
        echo "Failed to detect test disk size for powercycle plan." | tee -a "$Result_Dir/result.log"
        return 1
    fi

    rm -f "$Cur_Dir/$POWERCYCLE_PLAN_FILE" "$POWERCYCLE_STATE_NEXT_FILE"

    python3 "$Cur_Dir/powercycle_random.py" plan \
        --state "$POWERCYCLE_STATE_FILE" \
        --staged-state "$POWERCYCLE_STATE_NEXT_FILE" \
        --csv "$Cur_Dir/$POWERCYCLE_PLAN_FILE" \
        --current-loop "$loop" \
        --total-loops "$LOOP" \
        --min-disk-size-bytes "$min_disk_size" | tee -a "$Result_Dir/result.log"
    if [[ ${PIPESTATUS[0]} -ne 0 ]]; then
        echo "Failed to generate random powercycle plan." | tee -a "$Result_Dir/result.log"
        return 1
    fi

    filename="$POWERCYCLE_PLAN_FILE"
    echo "Use generated powercycle plan file: $filename" | tee -a "$Result_Dir/result.log"
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
	timeout 30 bash -c "dmesg -T > '$SystemLog/dmesg_${suffix}.log'" 2>/dev/null

    # Add IPMI SEL collection as requested
    if command -v ipmitool >/dev/null 2>&1; then
        echo "  - Collecting IPMI SEL..."
        timeout 30 bash -c "ipmitool sel list > '$SystemLog/ipmi_sel_${suffix}.log'" 2>/dev/null
    fi

    echo "********** Log collection complete (Suffix: ${suffix}) **********"
}

test_end()
{
    echo ""
    echo "=========================================="
    echo "********** ALL TESTS COMPLETE **********"
    echo "=========================================="
    echo "********** NVME RAID Test Engine Exit **********"
    exit 0
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






function partition(){
    disk_partition=$1
    totoal_num=$2
    disk_size=$3
    for ((i=1; i<=$totoal_num; i++));do
        fdisk /dev/$disk_partition  <<eof
n


+${disk_size}G
w
eof
    partprobe /dev/${disk_partition}
    done
}

function del_partition(){
    local disk_del=$1
    umount -l /dev/$disk_del* 2>/dev/null
    wipefs -a /dev/$disk_del
    fdisk /dev/$disk_del  <<eof
g
w
eof
}

function mount_disk(){
    disk_mount=$1
    mkdir -p /tmp/fiotest/$disk_mount
    mount /dev/$disk_mount /tmp/fiotest/$disk_mount
    touch /tmp/fiotest/${disk_mount}/test_${disk_mount}
}


function prepare_filesystem(){
    if [ -d /tmp/fiotest/ ]; then
        mount | grep "/tmp/fiotest/" | awk '{print $3}' | xargs umount -l 2>/dev/null
    fi
    rm -rf /tmp/fiotest/
    add_disks=()
    add_disk_num=0
    for hd in ${disk[*]};do
	    del_partition $hd
    done
    wait
    sleep 10
    partprobe
    lsblk | awk '{print $1}' > before.disk
    for hd in ${disk[*]};do
        disk_capacit_B=$(fdisk -l | grep "/dev/${hd}" | sed -n '1p' | awk '{print $5}')
        disk_capacit_G=`echo "$disk_capacit_B/1024/1024/1024" | bc`
        partition_num=8
        partition_size=`echo "scale=0;$disk_capacit_G/8" | bc`
        partition $hd $partition_num $partition_size &
    done
    wait
    partprobe
    sleep 60
    for hd in ${disk[*]};do
        partprobe /dev/$hd
    done
    sleep 10
    lsblk | awk '{print $1}' > after.disk
    add_disk=(`sort before.disk after.disk | uniq -u | sed 's/.*\([sn][dv].*\)/\1/'`)
    for hd in ${add_disk[*]};do
        add_disks[${#add_disks[*]}]=$hd
    done
        	
    echo ${add_disks[*]} 
    add_file=()
    mkdir -p /tmp/fiotest
    for ((i=0; i<${#add_disks[*]}; i++));do
        mkfs.xfs /dev/${add_disks[$i]} -f &
    done
    wait
    sleep 10
    for ((i=0; i<${#add_disks[*]}; i++));do
	    mount_disk ${add_disks[$i]} &
    done
    wait
    sleep 10
    echo "try to generate file for fio"
    for ((i=0; i<${#add_disks[*]}; i++));do
        dd if=/dev/zero of=/tmp/fiotest/${add_disks[$i]}/test_${add_disks[$i]} bs=1G count=10 conv=fsync &
	add_file[$i]="/tmp/fiotest/${add_disks[$i]}/test_${add_disks[$i]}"
    done
    wait
    sleep 20
    echo ${add_file[*]}
}

function close_mount(){
    sleep 10
    for ((i=0; i<${#add_disks[*]}; i++));do
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
        config_file="$count-$mode_-$blocksize-$iodepth-$run_time.log"

        sed -i '/randrepeat/d' $Cur_Dir/configuration.tmp
        sed -i '/norandommap/d' $Cur_Dir/configuration.tmp
        sed -i '/ramp_time/d' $Cur_Dir/configuration.tmp
        sed -i '/verify=/d' $Cur_Dir/configuration.tmp
        sed -i '/verify_fatal=/d' $Cur_Dir/configuration.tmp
        sed -i '/verify_dump=/d' $Cur_Dir/configuration.tmp
        sed -i '/verify_only=/d' $Cur_Dir/configuration.tmp
        sed -i '/do_verify=/d' $Cur_Dir/configuration.tmp
        sed -i '/size=/d' $Cur_Dir/configuration.tmp
        if [[ $disk_mode == "SUBALL" ]];then
            sed -i '/group_reporting/d' $Cur_Dir/configuration.tmp
        fi

        if [[ $item =~ "STRESS" ]];then

            sed -i "9i randrepeat=0"  $Cur_Dir/configuration.tmp
            sed -i "9i norandommap"  $Cur_Dir/configuration.tmp
            sed -i "9i ramp_time=5" $Cur_Dir/configuration.tmp
        fi
        if [[ -n "$verify_mode" ]]; then
            sed -i '/runtime=/d' $Cur_Dir/configuration.tmp
            sed -i '/time_based/d' $Cur_Dir/configuration.tmp
            sed -i "9i size=config_size" $Cur_Dir/configuration.tmp
            sed -i "9i verify_dump=1" $Cur_Dir/configuration.tmp
            sed -i "9i verify_fatal=1" $Cur_Dir/configuration.tmp
            sed -i "9i verify=config_verify_type" $Cur_Dir/configuration.tmp
            if [[ "$verify_mode" == "VERIFY" ]]; then
                sed -i "9i verify_only=1" $Cur_Dir/configuration.tmp
            else
                sed -i "9i do_verify=0" $Cur_Dir/configuration.tmp
            fi
        fi
        sed  "s/config_blocksize/$blocksize/" $Cur_Dir/configuration.tmp > $Config_Dir/$config_file
        sed -i "s/config_mode/$mode_/" $Config_Dir/$config_file
        sed -i "s/run_time/$run_time/" $Config_Dir/$config_file
        sed -i "s/config_iodepth/$iodepth/" $Config_Dir/$config_file
        sed -i "s/num_jobs/$numjobs/" $Config_Dir/$config_file
        sed -i "s/read_percentage/$read_percentage/" $Config_Dir/$config_file
        if [[ -n "$verify_mode" ]]; then
            sed -i "s/off_set/${offset}/" $Config_Dir/$config_file
            sed -i "s/config_size/${io_size}/" $Config_Dir/$config_file
            sed -i "s/config_verify_type/${verify_type}/" $Config_Dir/$config_file
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

configure_mixio() {
    configure_filename="${File_Dir}/MixIO${1}.csv"
    
    echo "**********" `date +%m-%d" "%H:%M:%S` "Generating MIX IO Config Files**********"
    check_="START"
    line_t=2
    until [ "$check_" = "End" ]
    do
        line=`echo "$line_t"p`
        mode_rs=`sed -n "$line" $configure_filename |awk -F "," '{print $2}'`
        mode_rw=`sed -n "$line" $configure_filename |awk -F "," '{print $3}'`
        read_percentage=`sed -n "$line" $configure_filename |awk -F "," '{print $3}'`
        blocksize=`sed -n "$line" $configure_filename |awk -F "," '{print $1}'`
        # Skip commented lines or empty lines
        if [[ $blocksize =~ ^# ]] || [[ -z $blocksize ]]; then
            line_t=` expr $line_t + 1 `
            continue
        fi
        iodepth=`sed -n "$line" $configure_filename  |awk -F "," '{print $4}'`
        run_time=`sed -n "$line" $configure_filename |awk -F "," '{print $5}'`
        numjobs=`sed -n "$line" $configure_filename |awk -F "," '{print $6}'`
	offset=`sed -n "$line" $configure_filename |awk -F "," '{print $7}'`
        check_="$blocksize"
        if [ "$check_" = "End" ];then
            echo "Job files are under $Config_Dir/MIX$1"
            echo ""
            line_t=` expr $line_t + 1 `
            continue
        fi

        if [ "$mode_rs" -eq 100 ];then
            mode_rs=R
        elif [ "$mode_rs" -eq 0 ];then
            mode_rs=S
        else
            echo ""
        fi

        if [ "$mode_rw" -eq 100 ];then
            mode_rw=READ
        elif [ "$mode_rw" -eq 0 ];then
            mode_rw=WRITE
        else
            mode_rw=MIX
        fi

        if [[ $mode_rs == "R" ]] && [[ $mode_rw == "READ" ]];then
            mode_=randread
        fi

        if [ "$mode_rs" = "R" ] && [ "$mode_rw" = "WRITE" ];then
            mode_=randwrite
        fi

        if [ "$mode_rs" = "R" ] && [ "$mode_rw" = "MIX" ];then
            mode_=randrw
        fi

        if [ "$mode_rs" = "S" ] && [ "$mode_rw" = "READ" ];then
            mode_=read
        fi

        if [ "$mode_rs" = "S" ] && [ "$mode_rw" = "WRITE" ];then
            mode_=write
        fi

        if [ "$mode_rs" = "S" ] && [ "$mode_rw" = "MIX" ]; then
            mode_=rw
        fi

        if [ "$mode_rw" = "MIX" ];then
            sed -i '/rwmixread/d' $Cur_Dir/configuration.tmp
            sed -i '8i rwmixread=read_percentage' $Cur_Dir/configuration.tmp
        fi

        if [ "$mode_rw" != "MIX" ];then
            sed -i '/rwmixread/d' $Cur_Dir/configuration.tmp
        fi

            count=` expr $line_t - 1 `
            config_file="$count-$mode_-$blocksize-$iodepth-$run_time.log"

            sed -i '/randrepeat/d' $Cur_Dir/configuration.tmp
            sed -i '/norandommap/d' $Cur_Dir/configuration.tmp
            sed -i '/ramp_time/d' $Cur_Dir/configuration.tmp

            if [[ $item =~ "STRESS" ]];then

                sed -i "9i randrepeat=0"  $Cur_Dir/configuration.tmp
                sed -i "9i norandommap"  $Cur_Dir/configuration.tmp
                sed -i "9i ramp_time=5" $Cur_Dir/configuration.tmp
            fi
            sed  "s/config_blocksize/$blocksize/" $Cur_Dir/configuration.tmp > $Config_Dir/MIX${1}/$config_file
            sed -i "s/config_mode/$mode_/" $Config_Dir/MIX${1}/$config_file
            sed -i "s/run_time/$run_time/" $Config_Dir/MIX${1}/$config_file
            sed -i "s/config_iodepth/$iodepth/" $Config_Dir/MIX${1}/$config_file
            sed -i "s/num_jobs/$numjobs/" $Config_Dir/MIX${1}/$config_file
            sed -i "s/off_set/${offset}%/" $Config_Dir/MIX${1}/$config_file
            sed -i "s/read_percentage/$read_percentage/" $Config_Dir/MIX${1}/$config_file
	    sed -i "s/config_log_avg_msec/$log_interval/"  $Config_Dir/MIX${1}/$config_file

        
        line_t=` expr $line_t + 1 `
    done
}







function set_Disk()
{
    cp $Cur_Dir/configuration $Cur_Dir/configuration.tmp
    if [[ $disk_mode == ALL || $disk_mode == SUBALL ]];then
        if [[ $item == LAWDISKSTRESS || $item == REBOOT || $item == DC || $item == AC ]];then
            # 仅对非系统盘的裸设备下发 IO（系统盘已在 do_fio 中被排除，不再对系统盘做任何 IO）
            for str in ${disk[@]}
            do
                Hard_Disk="/dev/"$str
                echo "["$str"]" >>$Cur_Dir/configuration.tmp
                echo "filename="$Hard_Disk >>$Cur_Dir/configuration.tmp
                echo "size=100%" >>$Cur_Dir/configuration.tmp
            done
        elif [[ $item == FILESYSTEMSTRESS ]];then
            # 仅对非系统盘新建的文件系统做 IO，不在系统盘上创建任何测试文件
            prepare_filesystem
            echo "size=100%" >>$Cur_Dir/configuration.tmp
            for str in ${add_file[@]}
            do
                job_name=`echo $str | awk -F '/' '{print $4}'`
                echo "["$job_name"]" >>$Cur_Dir/configuration.tmp
                echo "filename="${str} >>$Cur_Dir/configuration.tmp 
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
    # Check for /boot first, then /
    local boot_mount=$(lsblk -rn | grep -E ' (/boot|/)$' | head -n 1)
    local boot_device=$(echo "$boot_mount" | awk '{print $1}')

    if [[ -z "$boot_device" ]]; then
        # Fallback if lsblk -rn doesn't work as expected
        boot_device=$(findmnt -nvo SOURCE / | sed 's/\[.*\]//')
    fi

    if [[ "$boot_device" =~ sd ]]; then
        system_disk=$(echo "$boot_device" | grep -oP "sd[a-z]+")
    elif [[ "$boot_device" =~ nvme ]]; then
        system_disk=$(echo "$boot_device" | grep -oP "nvme\d+n\d+")
    else
        # Generic fallback extraction
        system_disk=$(echo "$boot_device" | sed -r 's/p?[0-9]+$//' | sed 's/.*\///')
    fi
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


function result_handle_for_mix_io(){
    sleep 5
    for i in {1..4};do
        readiops=$(cat $Result_Dir/detresult/MIX${i}/${jobnum}.txt| grep "read:" | awk -F "IOPS=" '{print $2}' | awk -F "," '{print $1}')
        writeiops=$( cat $Result_Dir/detresult/MIX${i}/${jobnum}.txt | grep "write:" | awk -F "IOPS=" '{print $2}' | awk -F "," '{print $1}')
        readbw_temp=$(cat $Result_Dir/detresult/MIX${i}/${jobnum}.txt | grep "read:" | awk -F "BW=" '{print $2}' | awk -F "(" '{print $1}')
        writebw_temp=$( cat $Result_Dir/detresult/MIX${i}/${jobnum}.txt | grep "write:" | awk -F "BW=" '{print $2}' | awk -F "(" '{print $1}')
        Lat=$( cat $Result_Dir/detresult/MIX${i}/${jobnum}.txt | grep -i '[[:space:]]lat.*avg' | tail -n1 | awk -F "avg=" '{print $2}' | awk -F "," '{print $1}')
        CPUusr=$(cat $Result_Dir/detresult/MIX${i}/${jobnum}.txt | grep cpu | awk -F "usr=" '{print $2}' | awk -F "," '{print $1}')
        CPUsys=$(cat $Result_Dir/detresult/MIX${i}/${jobnum}.txt | grep cpu | awk -F "sys=" '{print $2}' | awk -F "," '{print $1}')
        
        jobs_run=$(cat $Config_Dir/MIX${i}/${jobnum}-*.log | awk '/numjobs/ {split($0,arr,"=");print arr[2]}')
	iodepth=$(cat $Config_Dir/MIX${i}/${jobnum}-*.log | grep iodepth | awk -F "=" '{print $2}')
        rw_temp=$(cat $Config_Dir/MIX${i}/${jobnum}-*.log | sed -n 7p | awk -F "=" '{print $2}')
        read_percentage=$(cat $Config_Dir/MIX${i}/${jobnum}-*.log | grep rwmixread | awk -F "=" '{print $2}')
        size=$(cat $Config_Dir/MIX${i}/${jobnum}-*.log | grep bs | awk -F "=" '{print $2}' | head -n1)
        run_time=$(cat $Config_Dir/MIX${i}/${jobnum}-*.log | grep runtime | awk -F "=" '{print $2}')
        if [ -z "$readiops" ]; then
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

        printf "%-10s %-12s %-10s %-12s %-10s %-10s %-8s %-18s %-18s %-12s %-11s %-10s %-10s\n" $rw, $iodepth, $size, $jobs_run, $readiops, $writeiops, $iops, $readbw, $writebw, $bw, $Lat, $CPUusr, $CPUsys >>$Result_Dir/MIX${i}/result.csv
        echo "**********" $(date +%m-%d" "%H:%M:%S) "Running FIO As All ${ttype}**********" >>$Result_Dir/MIX${i}/result.log
	echo "iodepth=$iodepth, transfer request size=$size, 100% $rw, runtime=$run_time, $jobs_run  " | tee -a $Result_Dir/MIX${i}/result.log
        echo "ReadIOPs=$readiops" | tee -a $Result_Dir/MIX${i}/result.log
        echo "WriteIOPs=$writeiops" | tee -a $Result_Dir/MIX${i}/result.log
        echo "IOPs=$iops" | tee -a $Result_Dir/MIX${i}/result.log
        echo "Readbw=$readbw" | tee -a $Result_Dir/MIX${i}/result.log
        echo "Writebw=$writebw" | tee -a $Result_Dir/MIX${i}/result.log
        echo "bw=$bw" | tee -a $Result_Dir/MIX${i}/result.log
        echo "Lat(usec)=$Lat" | tee -a $Result_Dir/MIX${i}/result.log
        echo "CPUusr=$CPUusr" | tee -a $Result_Dir/MIX${i}/result.log
        echo "CPUsys=$CPUsys" | tee -a $Result_Dir/MIX${i}/result.log
        echo -e "\n\n" | tee -a $Result_Dir/MIX${i}/result.log

    done


}






function run_single()
{
echo "**********" `date +%m-%d" "%H:%M:%S` "Running FIO As Single Mode,Reports For Single Disk **********"
num=`ls -p $Config_Dir | grep -v / | wc -l`
totalnum=$num
cd $Config_Dir
jobnum=1
#echo "Test-Mode,Queue-Depth,Blocksize,ReadIOPS,WriteIOPS,IOPS,Read_Bandwidth,Write_Bandwindth,Bandwidth,Latency,CPUusr%,CPUsys%"
for configuration in `ls -p $Config_Dir | grep -v / | sort -n -k 1 -t -`
do
   echo "fio $configuration"
   echo `date +%m-%d" "%H:%M:%S` >>$Result_Dir/detresult/"${loop}_$jobnum.txt"
#   fio "$configuration" >> $Result_Dir/detresult-single/"${loop}_$jobnum.txt"
   #test_disk=`echo ${test_disk[@]} | sed 's/,/ /g'`
   OLD_IFS="$IFS"
   IFS=" "
   test_disk=`echo ${test_disk[@]} | sed 's/,/ /g'`
   test_disk=($test_disk)
   IFS="$OLD_IFS"
   for str1 in ${test_disk[@]}
   do
      ####modify by wuwei for multi-threads
      echo "[$str1]" >>$configuration
      echo "filename=/dev/"$str1 >>$configuration
      if [[ $str1 =~ $system_disk ]];then
          echo "size=100%" >> $configuration
      fi
      ###################
      ####for BTP,do not modify this,please!!!####
      ################

      fio "$configuration" >> $Result_Dir/detresult/"${loop}_$jobnum.txt"
      local fio_rc=$?
      if [[ $fio_rc -ne 0 ]]; then
          echo "FIO command failed on disk ${str1}, config ${configuration}, rc=${fio_rc}" | tee -a $Result_Dir/result.log
          return $fio_rc
      fi


      sed -i '$d' $configuration
      sed -i '$d' $configuration

      result_handle_pre
      if [[ $jobnum == 1 ]];then
          printf "%-25s %-12s %-10s %-6s %-11s %-10s %-11s %-6s %-8s %-10s %-11s %-10s %-10s %-10s\n" sn, rw, iodepth, size, jobs_run, readiops, writeiops, iops, readbw, writebw, bw, Lat, CPUusr, CPUsys >> $Result_Dir/${str1}_${loop}.csv
       fi
       printf "%-25s %-12s %-10s %-6s %-11s %-10s %-11s %-6s %-8s %-10s %-11s %-10s %-10s %-10s\n" $sn, $rw, $iodepth, $size, $jobs_run, $readiops, $writeiops, $iops, $readbw, $writebw, $bw, $Lat, $CPUusr, $CPUsys >> $Result_Dir/${str1}_${loop}.csv
       echo "**********" $(date +%m-%d" "%H:%M:%S) "Running FIO As Single Disk**********" >>$Result_Dir/result.log
       echo "Test Disk: $sn--${str1}" | tee -a $Result_Dir/result.log

       result_handle_after
   done
   jobnum=`expr $jobnum + 1`
done
#cd $Result_Dir
#for file in `ls *.csv|grep -v "result.csv"`
#do
#   sed -i '1i\Serial_Number,Test_Disk,Test-Mode,Queue-Depth,Blocksize,ReadIOPS,WriteIOPS,IOPS,Read_Bandwidth,Write_Bandwindth,Bandwidth,Latency,CPUusr%,CPUsys%' $file
#done
#cd $Job_Dir
}
function run_all()
{
    if [[ $mix_io == NO ]];then
        cd $Config_Dir
        echo "**********" `date +%m-%d" "%H:%M:%S` "Running FIO As All Mode,Reports For ALL Disk  **********"
        num=`cat $Cur_Dir/$filename |grep -v -i 'End'|wc -l`
        totalnum=`expr $num - 1`
        jobnum=1
        printf "%-10s %-12s %-10s %-12s %-10s %-10s %-8s %-18s %-18s %-12s %-11s %-10s %-10s\n" Test-Mode, Queue-Depth, Blocksize, NumJbs, ReadIOPS, WriteIOPS, IOPS, Read_Bandwidth, Write_Bandwindth, Bandwidth, Latency, CPUusr%, CPUsys% >>$Result_Dir/result_$loop.csv
        rm -rf stor*
	for configuration in `ls -p $Config_Dir | grep -v / | sort -n -k 1 -t -`
        do
            echo `date +%m-%d" "%H:%M:%S` >>$Result_Dir/detresult/"${loop}_$jobnum.txt"
            echo "Job $jobnum/$totalnum is Running.."

            ###################
            ####for BTP,do not modify this,please!!!####
            ##################


            fio "$configuration" --write_bw_log=$LogAd/test-fio --write_iops_log=$LogAd/test-fio >> $Result_Dir/detresult/"${loop}_$jobnum.txt"
            local fio_rc=$?
            if [[ $fio_rc -ne 0 ]]; then
                echo "FIO command failed, config ${configuration}, rc=${fio_rc}" | tee -a $Result_Dir/result.log
                return $fio_rc
            fi

            result_handle_pre
            printf "%-10s %-12s %-10s %-12s %-10s %-10s %-8s %-18s %-18s %-12s %-11s %-10s %-10s\n" $rw, $iodepth, $size, $jobs_run, $readiops, $writeiops, $iops, $readbw, $writebw, $bw, $Lat, $CPUusr, $CPUsys >>$Result_Dir/result_$loop.csv
            echo "**********" $(date +%m-%d" "%H:%M:%S) "Running FIO As All Disk**********" >>$Result_Dir/result.log

            result_handle_after
            jobnum=`echo "$jobnum + 1" | bc -l`
        done
        cd $Job_Dir
    elif [[ $mix_io == YES ]];then
        echo "*********" `date +%m-%d" "%H:%M:%S` "Running MIX IO on All Mode, Reports For All Disk *********"
        num=`sed -n '2,$p' $File_Dir/MixIO1.csv | grep -v -i 'End' | wc -l`
        totalnum=$num
        for((jobnum=1;jobnum<=num;jobnum++));do
            echo `date +%m-%d" "%H:%M:%S` >>$Result_Dir/detresult/MIX1/$jobnum.txt
            echo `date +%m-%d" "%H:%M:%S` >>$Result_Dir/detresult/MIX2/$jobnum.txt
            echo `date +%m-%d" "%H:%M:%S` >>$Result_Dir/detresult/MIX3/$jobnum.txt
            echo `date +%m-%d" "%H:%M:%S` >>$Result_Dir/detresult/MIX4/$jobnum.txt

            echo "Job $jobnum/$totalnum is Running.."
              
            fio $Config_Dir/MIX1/$jobnum-*.log --write_bw_log=$LogAd/test-fio --write_iops_log=$LogAd/test-fio >>$Result_Dir/detresult/MIX1/$jobnum.txt &
            fio $Config_Dir/MIX2/$jobnum-*.log --write_bw_log=$LogAd/test-fio --write_iops_log=$LogAd/test-fio >>$Result_Dir/detresult/MIX2/$jobnum.txt &
            fio $Config_Dir/MIX3/$jobnum-*.log --write_bw_log=$LogAd/test-fio --write_iops_log=$LogAd/test-fio >>$Result_Dir/detresult/MIX3/$jobnum.txt &
            fio $Config_Dir/MIX4/$jobnum-*.log --write_bw_log=$LogAd/test-fio --write_iops_log=$LogAd/test-fio >>$Result_Dir/detresult/MIX4/$jobnum.txt 
       
            result_handle_for_mix_io 
        done

    fi
}

function run_suball()
{
    cd $Config_Dir
    echo "**********" `date +%m-%d" "%H:%M:%S` "Running FIO As Suball Mode,Reports For Single Disk **********"
    printf "%-25s %-12s %-10s %-6s %-11s %-10s %-11s %-6s %-8s %-10s %-11s %-10s %-10s %-10s\n" Disk, rw, iodepth, size, jobs_run, readiops, writeiops, iops, readbw, writebw, bw, Lat, CPUusr, CPUsys >> $Result_Dir/result_${loop}.csv
    num=`cat $Cur_Dir/$filename |grep -v -i 'End'|wc -l`
    totalnum=`expr $num - 1`
    jobnum=1
    #echo " Disk Test-Mode,Queue-Depth,Blocksize,ReadIOPS,WriteIOPS,IOPS,Read_Bandwidth,Write_Bandwindth,Bandwidth,Latency,CPUusr%,CPUsys%">> $Result_Dir/result_"$loop".csv
    for configuration in `ls -p $Config_Dir | grep -v / | sort -n -k 1 -t -`
    do
        echo `date +%m-%d" "%H:%M:%S` >>$Result_Dir/detresult/"${loop}_$jobnum.txt"
        echo "Job $jobnum/$totalnum is Running.."

        ###################
        ####for BTP,do not modify this,please!!!####
        ##################


        fio "$configuration" --write_bw_log=$LogAd/test-fio --write_iops_log=$LogAd/test-fio >> $Result_Dir/detresult/"${loop}_$jobnum.txt"
        local fio_rc=$?
        if [[ $fio_rc -ne 0 ]]; then
            echo "FIO command failed, config ${configuration}, rc=${fio_rc}" | tee -a $Result_Dir/result.log
            return $fio_rc
        fi

        OLD_IFS="$IFS"
        IFS=" "
        test_disk=`echo ${test_disk[@]} | sed 's/,/ /g'`
        test_disk=($test_disk)
        IFS="$OLD_IFS"
        #test_disk=`echo ${test_disk[@]} | sed 's/,/ /g'`
        for str1 in ${test_disk[@]}
        do
            echo "**************$str1"
            result_handle_pre
            if [[ $jobnum == 1 ]];then
                printf "%-25s %-12s %-10s %-6s %-11s %-10s %-11s %-6s %-8s %-10s %-11s %-10s %-10s %-10s\n" sn, rw, iodepth, size, jobs_run, readiops, writeiops, iops, readbw, writebw, bw, Lat, CPUusr, CPUsys >> $Result_Dir/${str1}_${loop}.csv

            fi
            printf "%-25s %-12s %-10s %-6s %-11s %-10s %-11s %-6s %-8s %-10s %-11s %-10s %-10s %-10s\n" $str1, $rw, $iodepth, $size, $jobs_run, $readiops, $writeiops, $iops, $readbw, $writebw, $bw, $Lat, $CPUusr, $CPUsys >> $Result_Dir/result_${loop}.csv
            printf "%-25s %-12s %-10s %-6s %-11s %-10s %-11s %-6s %-8s %-10s %-11s %-10s %-10s %-10s\n" $sn, $rw, $iodepth, $size, $jobs_run, $readiops, $writeiops, $iops, $readbw, $writebw, $bw, $Lat, $CPUusr, $CPUsys >> $Result_Dir/${str1}_${loop}.csv
            echo "**********" $(date +%m-%d" "%H:%M:%S) "Running FIO As SubAll Disk**********" >>$Result_Dir/result.log
            echo "Test Disk: $sn--${str1}" | tee -a $Result_Dir/result.log
            result_handle_after

        done
    jobnum=`echo "$jobnum + 1" | bc -l`
    done

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




function single_config()
{
   for conf in `ls -p $Config_Dir | grep -v / | sort -n -k 1 -t -`
   do
      sed -i '/group_reporting/d' $Config_Dir/$conf
   done
}


function change_config()
{
	for conf in `ls -p $Config_Dir | grep -v / | sort -n -k 1 -t -`
	do
        [ -f "$Config_Dir/$conf" ] || continue
	    sed -i '/time_based/d' $Config_Dir/$conf
	    sed -i '/runtime/d' $Config_Dir/$conf
	    sizeori=`sed -n '/size/p' $Config_Dir/$conf`
		if [[ "$item" == *STRESS ]]; then
			sizenew="size=100%"
			if [ "$sizeori" != "" ]; then
				sed -i "s/$sizeori/$sizenew/" $Config_Dir/$conf
			else
			 	sed -i "8i \\$sizenew\ " $Config_Dir/$conf
			fi
		elif [[ "$item" == "PERFORMANCE" ]];then
			sizenew="size=1%"
			if [ "$sizeori" != "" ]; then
				sed -i "s/$sizeori/$sizenew/" $Config_Dir/$conf
			else
			 	sed -i "8i \\$sizenew\ " $Config_Dir/$conf
			fi
		else
			echo "Input wrong test mode ($item), you can only input stress or performance"
			# return 1
		fi
   	done
}


function prepare()
{
    # 仅选取 TYPE=disk 的真实块设备，排除 loop/rom 等虚拟设备，并剔除系统盘
    disks=$(lsblk -dn -o NAME,TYPE | awk '$2=="disk"{print $1}' | grep -vw "$system_disk")
    i=1
    unset disk
    for str in $disks
    do
        mkdir -p /test_disk$i
        parted -s /dev/$str mklabel gpt
        parted -s /dev/$str mkpart primary 1 200G
        if [[ $str =~ nvme ]]; then
            part="/dev/${str}p1"
        else
            part="/dev/${str}1"
        fi
        mkfs -t "$fs_type" "$part"
        mount "$part" /test_disk$i
        touch /test_disk$i/test$i
        disk[${i}]=/test_disk$i/test$i
        i=`expr $i + 1`
    done
    sed -i '$a\size=Size' configuration
}


########Modify by wuwei for multithreads and random-configuration
single()
{
##modify by wuwei for random generating config
      jobnum=1
      for a in $config_list
      do
          rm -rf $Job_Dir/*.log >/dev/null
          rm -rf $Job_Dir/MIX* >/dev/null
          echo "(LOOP-Diskmode)$loop - single" >>$Result_Dir/result.log

          echo "Run $a" >>$Result_Dir/result.log
          echo "" >>$File_Dir/$a
          echo "End" >>$File_Dir/$a
          configure
          #single_config
          run_single $a
      done
cd $Result_Dir
for file in `ls *.csv|grep -v "result*.csv"`
do
   sed -i '1i\Serial_Number,Test_Disk,Test-Mode,Queue-Depth,Blocksize,ReadIOPS,WriteIOPS,IOPS,Read_Bandwidth,Write_Bandwindth,Bandwidth,Latency,CPUusr%,CPUsys%' $file
done
cd $Cur_Dir
}
all()
{
    rm -rf $Result_Dir/*.log $Result_Dir/*.html $Result_Dir/.fio*
    if [ "$mix_io" = "NO" ];then
        jobnum=1
        for b in $config_list
        do
            rm -rf $Job_Dir/*.log >/dev/null
            rm -rf $Job_Dir/MIX* >/dev/null
            echo "(LOOP-Diskmode)$loop - all" >>$Result_Dir/result.log
            echo "Run $b" >>$Result_Dir/result.log
            echo "" >>$File_Dir/$b
            echo "End" >>$File_Dir/$b
            configure
            run_all $b
        done
        if [[ -n "$loop" ]] && [ "$loop" -gt 1 ]; then
            comparebw
            if [ "$error_flag" = "true" ]; then
                echo "FIO + DC test fail occur great difference between $beforeloop and $loop,more detail message to see $result/error.log"
            fi
        fi
    elif [ "$mix_io" = "YES" ];then
	for i in 1 2 3 4;do
	    mkdir -p $Config_Dir/MIX$i
            mkdir -p $Result_Dir/MIX$i
            mkdir -p $Result_Dir/detresult/MIX$i
            printf "%-10s %-12s %-10s %-12s %-10s %-10s %-8s %-18s %-18s %-12s %-11s %-10s %-10s\n" Test-Mode, Queue-Depth, Blocksize, NumJbs, ReadIOPS, WriteIOPS, IOPS, Read_Bandwidth, Write_Bandwindth, Bandwidth, Latency, CPUusr%, CPUsys% >>$Result_Dir/MIX$i/result.csv
            configure_mixio $i
	done
        run_all
    fi
}

sub_all()
{
##modify by wuwei for random generating config
      #cp $Cur_Dir/configuration $Cur_Dir/configuration.tmp
      jobnum=1
#      echo "Test-Mode,Queue-Depth,Blocksize,ReadIOPS,WriteIOPS,IOPS,Read_Bandwidth,Write_Bandwindth,Bandwidth,Latency,CPUusr%,CPUsys%">> $Result_Dir/result.csv
      for b in $config_list
      do
          rm -rf $Job_Dir/*.log >/dev/null
          rm -rf $Job_Dir/MIX* >/dev/null

          echo "(LOOP-Diskmode)$loop - suball" >>$Result_Dir/result.log
          echo "Run $b" >>$Result_Dir/result.log
          echo "" >>$File_Dir/$b
          echo "End" >>$File_Dir/$b
          configure
          run_suball $b
      done
#      if [ "$loop" -gt 1 ]; then
#        comparebw
#        if [ "$error_flag" = "true" ]; then
#                echo "FIO + DC test fail occur great difference between $beforeloop and $loop,more detail message to see $result/error.log"
#                #exit 1
#        fi
#      fi

}

function get_config_filelist() {
    rm -rf $File_Dir/*
    if [[ $mix_io == NO ]];then
        cp -r $Cur_Dir/$filename $File_Dir/ >/dev/null
        # Only append End to the copy in File_Dir if not already present
        if ! grep -q "End" $File_Dir/$filename; then
            echo "End" >> $File_Dir/$filename
        fi
        
        rm -rf $Cur_Dir/config_list1.log
        ls -p $File_Dir | grep -v / | grep "\.csv" | awk '{print $NF}' > $Cur_Dir/config_list.log
        while read i
        do
            echo "$i $RANDOM"
        done<$Cur_Dir/config_list.log|sort -k2n|cut -d " " -f1>$Cur_Dir/config_list1.log
        #rm -rf $Cur_Dir/config_list.log >/dev/null &
        config_list=`cat $Cur_Dir/config_list1.log`
        rm -rf $Cur_Dir/config_list.log >/dev/null
    elif [[ $mix_io == YES ]];then
        cd $File_Dir
	rm -rf MixIO*.csv
	for i in {1..4};do
	    python3 $Cur_Dir/random_choice.py
	    mv random_choice.csv MixIO$i.csv
	done
        cd $Cur_Dir
    fi
}



function do_stress(){

#sleep 300

###################
####for BTP, do not modify this,please!!!####
##################

sleep 1
sync
echo 3 > /proc/sys/vm/drop_caches

echo "runing"
do_reboot
sleep 1

}



function run_mode() {
    if [ "$disk_mode" = "BOTH" ];then
        all || return $?
        single || return $?
    elif [ "$disk_mode" = "ALL" ];then
        all || return $?
    elif [ "$disk_mode" = "SUBALL" ];then
        sub_all || return $?
    elif [ "$disk_mode" = "SINGLE" ];then
        single || return $?
    else
        echo "do not support disk mode $disk_mode"
        return 1
    fi
    return 0
}

function do_fio() {

        get_system_disk
        # 安全护栏：无法识别系统盘时直接中止，避免误把系统盘当作数据盘
        if [[ -z "$system_disk" ]];then
            echo -ne " Fail to detect system disk. Refuse to run to avoid any IO on OS disk. Exit.\n"
            exit 1
        fi
        if [[ "$specified_disk" =~ "null" ]];then
            # 仅选取 TYPE=disk 的真实块设备，排除 loop/rom 等虚拟设备；
            # 再用 -w 精确匹配整词剔除系统盘，确保绝不对系统盘或虚拟设备做 IO
            disk=$(lsblk -dn -o NAME,TYPE | awk '$2=="disk"{print $1}' | grep -vw "$system_disk" | sort)
            OLD_IFS="$IFS"
            IFS=" "
            disk=($disk)
            IFS="$OLD_IFS"
            test_disk=`echo ${disk[@]}|sed 's/ /,/g'`
        elif [[ $specified_disk =~ $system_disk ]];then
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

        echo -ne "System_Disk is $system_disk\n"
        echo -ne "The test disk is: $test_disk\n"
        if [ "$fs_type" != "NON-FS" ];then
            echo "**********" `date +%m-%d" "%H:%M:%S` "preparing **********"
            prepare
            change_config
        fi

        if powercycle_mode_enabled; then
            prepare_powercycle_plan || return $?
        fi

        get_config_filelist
        set_Disk
        run_mode || return $?
        if powercycle_mode_enabled; then
            commit_powercycle_state
        fi
        rm -rf $Cur_Dir/configuration.tmp*
        close_mount
        return 0
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

    while [ "$loop" -lt "$LOOP" ]
    do
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

    done

#    echo "FIO + DC test has been run $LOOP,it will be exit,if you want to run more times please modify the var loops"


}


function fio_cycle()
{
    cd ${Cur_Dir}
    sh run_fio.sh "$item" "$check" "$bmc_reset" "$flag" "$delay" "$mode" "$wait" "$port" "$server_ip" "$LOOP" "$acserverport" "$safe" "$sysStaticIP" "$blackBoxStaticIP" "$runtime" "$filename" "$fs_type" "$disk_mode" "$specified_disk" "$remote" "$mix_io" "$log_interval"
}
