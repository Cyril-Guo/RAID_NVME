#!/bin/bash
function arguments_parse()
{
    argvs=$@
    #if [ "$#" -eq 0 ];then
    #    echo "Invalid arguments, try '-h/--help' for more information."
    #    exit 1
    #fi
    while [[ "$1" != "" ]]
    do
        case $1 in
           -i)
	           shift
	           item=$1
               item=`echo $item|tr '[a-z]' '[A-Z]'`;;    ##DC or stress or release

           -c)
               shift
               check=$1
               check=`echo $check|tr '[a-z]' '[A-Z]'`;;

           -b)
	           shift
               bmc_reset=$1
               bmc_reset=`echo $bmc_reset|tr '[a-z]' '[A-Z]'`;; ##if bmc cold reset
           -f)
	           shift
               flag=$1
               flag=`echo $flag|tr '[a-z]' '[A-Z]'`;;   ##stop or continue
           -d)
	           shift
               delay=$1;;            ##Delay time, the wait time befor reboot
            -m)
	           shift
               mode=$1
               mode=`echo $mode|tr '[a-z]' '[A-Z]'`;;  ##for DC, UTC or RTC
           -w)
	           shift
               wait=$1;;  ##shut down time for DC
           -r)
               shift
               runtime=$1;;
           -n)
               shift
               filename=$1;;
           -t)
               shift
               fs_type=$1
               fs_type=`echo $fs_type|tr '[a-z]' '[A-Z]'`;;
           -o)
               shift
               disk_mode=$1
               disk_mode=`echo $disk_mode|tr '[a-z]' '[A-Z]'`;; ##All disks or single disk or both
           -u)
               shift
               specified_disk=$1
               specified_disk=`echo $specified_disk|tr '[A-Z]' '[a-z]'`;;
           -l)
               shift
               LOOP=$1;;
	   -q)
               shift
               log_interval=$1;;
           -x)
               shift
               remote=$1;;
	   --mix_io|-mix)
	       shift
	       mix_io=$1;;
           -h|--help)
               help
           exit;;
        *)
           echo "Invalid arguments, try '-h/--help' for more information."
           exit 1;;
        esac
	shift
    done
}

function help(){
   echo "Usage :" 
   echo "   DC run as:     $0 -i dc"
   echo "   stress run as:     $0 -i lawdiskstress  or  $0 -i filesystemstress"

   echo "   release run as: $0 -i release"
   echo "Optional Parameters:"
   echo "   DC: -m <RTC|UTC>: the default value is UTC"
   echo "   -i <lawdiskstress|filesystemstress|dc|reboot|restore>: run mode, default is lawdiskstress"
   echo "   -c <YES|NO>: If check the info, and the default is YES"
   echo "   -b <YES|NO>: If bmc cold reset or no, the default value is NO"
   echo "   -f <STOP|NON-STOP>: when diff occurs it will stop or not,the default is stop"
   echo "   -d <20|...>: S0 delay time,the default value is 10s"
   echo "   -w <60|...>: S5 delay time, the default value is 120s"
   echo "   -l <500|...>: the LOOPs, and the default value is 1000"
   #echo "   -r <43200|...>: runtime for stress"
   echo "   -n <Input_Config_Disk_Full_Scan.csv|...>: filename for stress only"
   echo "   -t <non-fs|...>: fs_type for stress"
   echo "   -o <all|single|both>: disk_mode for Disk"
   echo "   -u <sda,sdb,...>: specify disk"
   echo "   --mix_io|-mix <yes|no>: specify mix fio, default is no"
   echo "   -q <100|200|...>: log avg msec,default is 100"

   exit

}
function check_arguments()
{
    # Initialize loop counters if not set
    if [[ -z "$loop" ]]; then loop=1; fi
    if [[ -z "$beforeloop" ]]; then beforeloop=0; fi

    if [[ -z "$item" ]];then
	item="LAWDISKSTRESS"
        echo "**********" `date +%m-%d" "%H:%M:%S` "current mode is $item **********"
    fi
    if [[ -z "$delay" ]];then
        delay=10                           ##the default time of delay before reboot is 10s
    else
        expr $delay "+" 10 &> /dev/null
        if [ $? -ne 0 ];then
            echo "the input S0 delay time isn't a number,exit" 
            exit 1
        fi
    fi

    if [[ -z "$runtime" ]];then
        runtime=43200                           ##the default time of delay before reboot is 10s
    else
        expr $runtime "+" 10 &> /dev/null
        if [ $? -ne 0 ];then
            echo "the input runtime isn't a number,exit"
            exit 1
        fi
    fi


    if [[ -z "$check" ]];then
        check="YES"
    fi

    if [[ -z "$bmc_reset" ]];then
        bmc_reset="NO"
    fi
    if [[ -z "$flag" ]];then
        flag="STOP"                        ##stop when the diff occur by default
    fi
    if [[ -z "$LOOP" ]];then
        LOOP=3                         ##the default of runing time is 12h
    else
        expr $LOOP "+" 10 &> /dev/null
    if [ $? -ne 0 ];then
        echo "the input LOOP isn't a number,exit" 
        exit 1
    fi
    fi
    if [[ -z "$safe" ]];then
       safe="YES"
    fi
    if [[ $item == "PERFORMANCE" ]];then
        show_produce_message "Performance test start"
        LOOP=1
    elif [[ $item == "LAWDISKSTRESS" || $item == "FILESYSTEMSTRESS" ]];then
        show_produce_message "$item test start"
        LOOP=1
        #runtime=43200
#	    disk_mode="ALL"
        if [[ -z "$filename" ]];then
             filename="Input_Config_Disk_Full_Scan.csv"
        fi
    elif [[ $item == "REBOOT" ]];then
        show_produce_message "Reboot test start"
    elif [[ $item == "DC" ]];then
        if [[ -z "$mode" ]];then
            mode="UTC"
        fi

        if [[ -z "$wait" ]];then
            wait=120                 ##the default wait time of shutdown is 120s
        else
            expr $wait "+" 10 &> /dev/null
            if [ $? -ne 0 ];then
                echo "the input S5 delay time isn't a number,exit" 
                exit 1
            fi
        fi
        if [[ $mode == "UTC" ]];then
			show_produce_message "DC test start as UTC mode"
        elif [[ $mode == "RTC" ]];then
			show_produce_message "DC test start as RTC mode"
        else
            echo -e " the DC mode isn't supported, only utc or rtc, exit now.  \n"
            exit 1
        fi
    elif [[ $item == "RESTORE" ]];then
        show_produce_message "Restore mode selected"
    else
        echo -e " Unsupport test type,exit.  \n"
        exit 1
    fi

    if [[ -z "$mode" ]];then
        mode="null"
    fi
    if [[ -z "$wait" ]];then
        wait="null"
    fi

    ########
    if [[ -z "$fs_type" ]];then
         fs_type="NON-FS"

    fi



    if [[ -z "$disk_mode" ]];then
        disk_mode="ALL"
    fi


    if [[ -z "$filename" && "$item" != "DC" && "$item" != "REBOOT" ]];then
        filename="Input_Config_Disk_Full_Scan.csv"
    fi
    if [[ -z "$specified_disk" ]];then
        specified_disk="null"
    fi

    if [[ -z "$remote" ]];then
        remote="-"
    fi

    if [[ -z "$mix_io" ]];then
        mix_io=NO
    else
        mix_io=$(echo "$mix_io" | tr '[a-z]' '[A-Z]')
    fi
    if [[ $item == "DC" ]];then
        flag="NON-STOP"
    fi
    if [[ -z "$log_interval" ]];then
        log_interval=100                           ##the default time of delay before reboot is 10s
    else
        expr $log_interval "+" 10 &> /dev/null
        if [ $? -ne 0 ];then
            echo "the input log_interval isn't a number,exit"
            exit 1
        fi
    fi
    #######
}
