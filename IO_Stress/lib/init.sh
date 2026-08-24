#!/bin/bash

function clear_log()
{

    rm -rf $Result_Dir
    rm -rf $Config_Dir
    rm -rf $LogAd
    rm -rf $File_Dir
    # Removed nmon pkill



    mkdir -p $LogAd >/dev/null
    mkdir -p $File_Dir >/dev/null
    mkdir -p $Cur_Dir/job_files >/dev/null
    mkdir -p $Cur_Dir/job_files/MIX1 >/dev/null
    mkdir -p $Cur_Dir/job_files/MIX2 >/dev/null
    mkdir -p $Cur_Dir/job_files/MIX3 >/dev/null
    mkdir -p $Cur_Dir/job_files/MIX4 >/dev/null
    mkdir -p $Result_Dir/detresult >/dev/null
    mkdir -p $TestErrorLog
    mkdir -p $ResultLog
    mkdir -p $RawLog
    mkdir -p $MachineCheckLog > /dev/null
	mkdir -p $MessageRecordLog > /dev/null
	mkdir -p $SmartErrorLog/CheckNoStop > /dev/null
	mkdir -p $SystemLog > /dev/null


   
	show_produce_message "prepare test log directories"
    echo "  - System logs, dmesg, and IPMI SEL are preserved."
}

function prepare_logfile()
{
    rm -rf /root/.bash_profile.bak
    echo "Loop   time   reboot_time" > $ResultLog/reboot.log
    echo "0 `date +%s` " >> $ResultLog/reboot.log
}

function stop_sendmail()
{
    if [[ $System_Redhat7 == "1" ]] || [[ $System_CentOS8 == "1" ]]; then
        service sendmail stop 2>/dev/null
        chkconfig --levels 12345 sendmail off 2>/dev/null
    fi
}

function install_tools(){
    echo "  - Checking and installing dependencies (online)..."
    if [[ -f /etc/os-release ]]; then
        source /etc/os-release
        case $ID in
            ubuntu|debian)
                apt-get update >/dev/null 2>&1
                apt-get -y install gawk nmap bc psmisc sysstat numactl lsscsi python3-pip python-is-python3 unzip make gcc g++ nvme-cli sdparm smartmontools fio xfsprogs parted >/dev/null 2>&1
                ;;
            centos|rocky|rhel|fedora)
                yum install -y gawk nmap bc psmisc sysstat numactl lsscsi unzip make gcc gcc-c++ nvme-cli sdparm smartmontools fio xfsprogs parted >/dev/null 2>&1 || dnf install -y gawk nmap bc psmisc sysstat numactl lsscsi unzip make gcc gcc-c++ nvme-cli sdparm smartmontools fio xfsprogs parted >/dev/null 2>&1
                ;;
        esac
    fi
    echo "  - Dependency check complete."
}

function check_baseboardsn()
{
    baseboard_sn=`dmidecode -t baseboard|grep -i "Serial Number"|awk -F":" '{print $2}'|sed 's/^[[:space:]]*//g'|sed -n '/^[0-9a-zA-Z]*/p'|grep -v -E "TBD|NA|N\/A"`
}


function process_machinecheck_results() {
    local target_info_log=$1
    local target_check_log=$2
    local target_msg_log=$3

    if [[ -f $MachineCheck_Dir/Result/machinecheck.log ]]; then
        cp -rf $MachineCheck_Dir/Result/machinecheck.log "$target_info_log"
    fi
    if [[ -f $MachineCheck_Dir/Result/information_record.log ]]; then
        cp -rf $MachineCheck_Dir/Result/information_record.log "$target_msg_log"
    fi
    if [[ -f $MachineCheck_Dir/Result/error_disk_raw.log ]] && [[ -n $MachineCheckLog ]]; then
        cp -rf $MachineCheck_Dir/Result/error_disk_raw.log $MachineCheckLog/error_disk_raw.log
    fi

    if [[ -f $MachineCheck_Dir/Result/check.log ]]; then
        sed -i '/SSSTC.*171/d' $MachineCheck_Dir/Result/check.log
        sed -i '/SSSTC.*172/d' $MachineCheck_Dir/Result/check.log
        sed -i '/SSSTC.*175/d' $MachineCheck_Dir/Result/check.log
        sed -i '/RSYE.*5/d' $MachineCheck_Dir/Result/check.log
        sed -i '/RSYE.*171/d' $MachineCheck_Dir/Result/check.log
        sed -i '/RSYE.*172/d' $MachineCheck_Dir/Result/check.log
        sed -i '/RSYE.*184/d' $MachineCheck_Dir/Result/check.log
        sed -i '/RSYE.*187/d' $MachineCheck_Dir/Result/check.log
        if [[ -n $target_check_log ]]; then
            mkdir -p "$(dirname "$target_check_log")" >/dev/null 2>&1 || true
            cat $MachineCheck_Dir/Result/check.log > "$target_check_log"
        fi
    fi

}

function info_check(){
   if [[ $check == "NO" ]];then
      echo "Don't collect any info both HW and SW!"
   else
 	    show_produce_message "start first machinecheck"
      cd $MachineCheck_Dir >/dev/null
      rm -rf $MachineCheck_Dir/Disk_info/* >/dev/null
      bash MachineCheck.sh

      process_machinecheck_results "$MachineCheckLog/info_before.log" "$SmartErrorLog/CheckNoStop/check_nostop_before.log" "$MessageRecordLog/messages_record_before.log"
      
      if [[ -f $MachineCheckLog/info_before.log ]]; then
          echo "Machinecheck finish" >> $MachineCheckLog/info_before.log
      fi
      if [ -f "$MachineCheck_Dir/upi_speed_illegal.flag" ]; then
          echo "UPI Speed is slow,and exit now..."
          exit 1
      fi
      cd - >/dev/null
      sleep 5
   fi
}
function UPICheck(){
   local upi_info=$(lspci | grep -i "205b")
   if [ -n "$upi_info" ]; then
      # Original logic check for linenum=0 was unreachable with [ -s tmp ] or -n check
      # keeping it as a generic check for UPI presence if needed, but cleaner.
      echo "UPI controllers found in lspci."
   fi
}






function get_machinecheck()
{
	if [[ -d $MachineCheck_Dir ]];then
        echo -e " The machinecheck exists. The program continues to run.  \n"
    else
        echo -e " MachineCheck toolkit not found. Skipping machine check.  \n"
    fi
}


function intializer()
{
   clear_log
   prepare_logfile
   install_tools
   get_machinecheck
   stop_sendmail
   UPICheck
}

