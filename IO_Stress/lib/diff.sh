#!/bin/bash

IFS=$'\n'

# Compare only stable inventory fields. Ignore banners, tool versions, CPU summary, timestamps.
machinecheck_fingerprint() {
    local file="$1"
    sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//' "$file" | awk '
        $1 == "disk:" || $1 == "pcie_nvme:" || $1 == "link:" || $1 == "aer:" { print; next }
        $1 == "disk" && $2 == "count:" { print; next }
        $1 == "pcie_nvme" && $2 == "count:" { print; next }
    ' | sort
}

function record_errorinfo(){
    local fp_before fp_after
    fp_before=$(mktemp)
    fp_after=$(mktemp)
    machinecheck_fingerprint "$MachineCheckLog/info_before.log" > "$fp_before"
    machinecheck_fingerprint "$MachineCheckLog/info_after.log" > "$fp_after"

    echo "ERROR: MachineCheck Log Inconsistency Detected!" | tee -a $TestErrorLog/machine_diff_error.log
    echo "==================================================" | tee -a $TestErrorLog/machine_diff_error.log
    echo "Current Loop: $loop" | tee -a $TestErrorLog/machine_diff_error.log
    echo "Time: $(date)" | tee -a $TestErrorLog/machine_diff_error.log
    echo "Whitelist field differences (Golden < vs Current >):" | tee -a $TestErrorLog/machine_diff_error.log
    
    diff -u "$fp_before" "$fp_after" >> $TestErrorLog/machine_diff_error.log
    
    echo "--------------------------------------------------" >> $TestErrorLog/machine_diff_error.log
    echo -e " ERROR: MachineCheck inconsistencies found at loop $loop. Check $TestErrorLog/machine_diff_error.log for details."
    
    # Also record to diff_all.log
    echo -e "\n--- Loop $loop Error Record ---" >> $MessageRecordLog/diff_all.log
    diff -u "$fp_before" "$fp_after" >> $MessageRecordLog/diff_all.log
    rm -f "$fp_before" "$fp_after"
}

function diff_messages()
{
    if [[ $check == "NO" ]];then
        echo "no check,exit"
        echo "diff finish" >$LogAd/diff.flag
        return 1
    else
        show_produce_message "Computed FIO deviation"
        if [[ -n "$loop" && "$loop" != "0" ]];then
            date +%Y-%m-%d_%H:%M:%S | tee -a $Fio_Result_Dir/result_fio.log
            if [[ -f $Fio_Result_Dir/result_0.csv && -f $Fio_Result_Dir/result_${loop}.csv ]]; then
                fio_mode_list=($(cat $Fio_Result_Dir/result_0.csv 2>/dev/null | sed -n '2,$p' | awk '{print $1}'))
                for fio_mode in ${fio_mode_list[*]};do
                    if [[ ! $fio_mode ]];then continue; fi
                    before_iops=$(cat $Fio_Result_Dir/result_0.csv 2>/dev/null | grep "^$fio_mode" | awk '{print $7}' | awk -F, '{print $1}')
                    after_iops=$(cat $Fio_Result_Dir/result_${loop}.csv 2>/dev/null | grep "^$fio_mode" | awk '{print $7}' | awk -F, '{print $1}')
                    
                    # Ensure values are numbers before processing
                    [[ -z "$before_iops" || -z "$after_iops" ]] && continue

                    # ... (Handle 'k' in IOPS as before) ...
                    if [[ $before_iops =~ k ]]; then before_iops=$(echo "$before_iops" | awk -Fk '{print $1}' | awk '{print $1*1000}'); fi
                    if [[ $after_iops =~ k ]]; then after_iops=$(echo "$after_iops" | awk -Fk '{print $1}' | awk '{print $1*1000}'); fi
                    
                    before_bw=$(cat $Fio_Result_Dir/result_0.csv 2>/dev/null | grep "^$fio_mode" | awk '{print $11}' | awk -FM '{print $1}')
                    after_bw=$(cat $Fio_Result_Dir/result_${loop}.csv 2>/dev/null | grep "^$fio_mode" | awk '{print $11}' | awk -FM '{print $1}')
                    
                    [[ -z "$before_bw" || -z "$after_bw" ]] && continue

                    echo "$fio_mode" | tee -a $Fio_Result_Dir/result_fio.log
                    echo "Before Value: IOPS $before_iops, BW $before_bw" | tee -a $Fio_Result_Dir/result_fio.log
                    echo "After Value: IOPS $after_iops, BW $after_bw" | tee -a $Fio_Result_Dir/result_fio.log
                    
                    deviation_iops=$(echo "scale=2; if($after_iops > $before_iops) ($after_iops-$before_iops)/$before_iops*100 else ($before_iops-$after_iops)/$before_iops*100" | bc 2>/dev/null)
                    deviation_bw=$(echo "scale=2; if($after_bw > $before_bw) ($after_bw-$before_bw)/$before_bw*100 else ($before_bw-$after_bw)/$before_bw*100" | bc 2>/dev/null)
                    echo "Deviation: IOPS ${deviation_iops-0}%, BW ${deviation_bw-0}%" | tee -a $Fio_Result_Dir/result_fio.log
                done
            else
                echo "Wait for first complete loop to show performance deviation..."
            fi
        fi
        
        cd $MachineCheck_Dir >/dev/null
        show_produce_message "Start MachineCheck"
        bash MachineCheck.sh

        # compare_log
        if [[ -f $MachineCheck_Dir/Result/machinecheck.log ]]; then
            process_machinecheck_results "$MachineCheckLog/info_after.log"
        else
            echo "Warning: MachineCheck.sh did not produce machinecheck.log" | tee -a $Result_Dir/result.log
        fi

        if [[ -f $MachineCheckLog/info_after.log ]]; then
            echo "Machinecheck finish" >> $MachineCheckLog/info_after.log
            cp -f $MachineCheckLog/info_after.log $MachineCheckLog/${loop}_machinecheck.log
        fi
        
        # Whitelist field Diff Detection (disk/pcie_nvme/link/aer + counts)
        if [[ ! -f $MachineCheckLog/info_before.log ]] || [[ ! -f $MachineCheckLog/info_after.log ]]; then
            echo "Warning: Missing log files for diff comparison." | tee -a $Result_Dir/result.log
        else
            local fp_before fp_after
            fp_before=$(mktemp)
            fp_after=$(mktemp)
            machinecheck_fingerprint "$MachineCheckLog/info_before.log" > "$fp_before"
            machinecheck_fingerprint "$MachineCheckLog/info_after.log" > "$fp_after"
            if ! diff -q "$fp_before" "$fp_after" > /dev/null; then
                rm -f "$fp_before" "$fp_after"
                record_errorinfo
                echo "diff finish" >$LogAd/diff.flag
                return 3
            fi
            rm -f "$fp_before" "$fp_after"
        fi
    fi
    echo "diff finish" >$LogAd/diff.flag
    return 1
}



########################################################################################################
function info_diff()
{
    sleep 30




    diff_messages
    if [ $? -eq 3 ]; then
        if [ $flag == "STOP" ];then
            echo "stop_flag is STOP,so exit"
            collect_log
            test_end
        elif [ "$flag" == "NON-STOP" ];then
            echo "stop_flag is NON-STOP, ignore error and continue..."
            return 0
        else
            echo "Unsupport stop flag, and it shoule be STOP or NON-STOP, exit..."
            exit
        fi
    fi
}  
