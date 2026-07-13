#!/usr/bin/env bash
#/bin/bash

function clear_bashprofile()
{
    line=`cat /root/.bash_profile | grep -n "grep tty1" | sed -n '1p' | awk -F ":" '{print $1}'` > /dev/null
    if [[ ${line} != "" ]];then
        sed -i '/grep tty1/,$d' /root/.bash_profile
    fi
}
function install_smartctl()
{
    if ! command -v smartctl &> /dev/null; then
        echo "Installing smartmontools..."
        if command -v apt-get &> /dev/null; then
            apt-get update &>/dev/null
            apt-get install -y smartmontools &>/dev/null
        elif command -v yum &> /dev/null; then
            yum install -y smartmontools &>/dev/null
        elif command -v dnf &> /dev/null; then
            dnf install -y smartmontools &>/dev/null
        fi
    fi
}

function install_fio()
{
    need_install=false
    if ! command -v fio &> /dev/null; then need_install=true; fi
    if ! command -v mkfs.xfs &> /dev/null; then need_install=true; fi
    if ! command -v parted &> /dev/null; then need_install=true; fi
    if ! command -v iostat &> /dev/null; then need_install=true; fi

    if [[ $need_install == true ]]; then
        echo "Dependencies missing, installing online..."
        if command -v apt-get &>/dev/null; then
            apt-get update >/dev/null 2>&1
            apt-get install -y fio sysstat xfsprogs parted util-linux >/dev/null 2>&1
        elif command -v yum &>/dev/null; then
            yum install -y fio sysstat xfsprogs parted util-linux >/dev/null 2>&1
        elif command -v dnf &>/dev/null; then
            dnf install -y fio sysstat xfsprogs parted util-linux >/dev/null 2>&1
        fi
        
        if command -v fio &> /dev/null; then
            echo "FIO installation success."
            touch $Cur_Dir/fio_install.flag
        else
            echo "FIO installation fail, please check network or install manually."
            exit 1
        fi
    fi
}

function dotrap()
{
   trap '
    # Cleanup background monitoring if any
    ps -ef | grep -E "APERF_FREQ|python3 main.py" | grep -v grep | awk "{print \$2}" | xargs kill -9 > /dev/null 2>&1

    exit 0' EXIT 2
}

function autologin()
{
	show_produce_message "autologin"
    if [[ ${system_SLES11SP3} == "1" || ${system_SLES11SP2} == "1" ]]; then
        sed -i 's/id:5:initdefault:/id:3:initdefault:/' /etc/inittab
        sed -i 's#1:2345:respawn:/sbin/mingetty --noclear tty1#1:2345:respawn:/sbin/mingetty --noclear --autologin root tty1#' /etc/inittab
    elif [[ $System_Sugon == 1 ]];then
        #sudo ln -sf /lib/systemd/system/multi-user.target /lib/systemd/system/default.target
        sudo systemctl set-default graphical.target
        #sudo ln -sf /lib/systemd/system/graphical.target /lib/systemd/system/default.target
        sudo sed -i "s#ExecStart=.*#ExecStart=-/sbin/agetty --noclear --autologin root %I \$TERM#" /lib/systemd/system/getty@.service
        if [ -L /etc/systemd/system/getty.target.wants/getty@tty1.service ];then
                sudo rm /etc/systemd/system/getty.target.wants/getty@tty1.service
        fi
        sudo systemctl enable getty@tty1.service
   elif [[ $System_NFS_PC5 != 0 ]];then
    #sudo ln -sf /lib/systemd/system/multi-user.target /lib/systemd/system/default.target
    #sudo systemctl set-default graphical.target
    #sudo ln -sf /lib/systemd/system/graphical.target /lib/systemd/system/default.target
    sudo sed -i "s#ExecStart=.*#ExecStart=-/sbin/agetty --noclear --autologin root %I \$TERM#" /lib/systemd/system/getty@.service
#    if [ -L /etc/systemd/system/getty.target.wants/getty@tty1.service ];then
#            sudo rm /etc/systemd/system/getty.target.wants/getty@tty1.service
#    fi
#    sudo systemctl enable getty@tty1.service
    elif [[ ${system_SLES12} == "1" ]]; then
        ln -sf /usr/lib/systemd/system/multi-user.target /etc/systemd/system/default.target
        sed -i 's#ExecStart=-/sbin/agetty --noclear %I $TERM#ExecStart=-/sbin/agetty --noclear --autologin root %I $TERM#' /usr/lib/systemd/system/getty@.service
    elif [[ ${system_Redhat5} == "1" ]]; then
        sed -i 's/id:5:initdefault:/id:3:initdefault:/' /etc/inittab
        sed -i 's#1:2345:respawn:/sbin/mingetty tty1#1:2345:respawn:/sbin/mingetty --noclear --autologin root tty1#' /etc/inittab
    elif [[ ${system_Redhat6} == "1" ]]; then
        sed -i 's/id:5:initdefault:/id:3:initdefault:/' /etc/inittab
        sed -i 's#exec /sbin/mingetty#exec /sbin/mingetty --autologin root#' /etc/init/tty.conf
    elif [[ $system_CentOS6 == "1" ]]; then
        sed -i 's/id:5:initdefault:/id:3:initdefault:/' /etc/inittab
        sed -i 's#exec /sbin/mingetty#exec /sbin/mingetty --autologin root#' /etc/init/tty.conf
    elif [[ ${system_Redhat7} == "1" ]] || ([ -f /etc/os-release ] && grep -iq "Ubuntu" /etc/os-release) && [[ ${system_CentOS8} != "1" ]]; then
        if [ -f /etc/os-release ] && grep -iq "Ubuntu" /etc/os-release ; then
            # Ubuntu: Use a dedicated systemd service for maximum reliability on modern versions (e.g. 25.04)
            show_produce_message "Setting up Systemd fio-test.service for Ubuntu"
            abs_root=$(cd "$CP_ROOT_DIR"; pwd)
            
            # Use "Nuclear" TTY option: disable existing getty on tty3 to avoid conflict
            systemctl stop getty@tty3.service >/dev/null 2>&1
            systemctl mask getty@tty3.service >/dev/null 2>&1

            # Create the service file with full TTY ownership
            cat > /etc/systemd/system/fio-test.service <<EOF
[Unit]
Description=Fio Reboot/DC Test Service
After=multi-user.target
Conflicts=getty@tty3.service

[Service]
Type=simple
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ExecStartPre=/bin/sleep 30
ExecStart=/bin/bash -c "/usr/bin/logger 'FIO_SERVICE_STARTING_ON_TTY3' && /bin/bash $abs_root/run_fio.sh \"$item\" \"$check\" \"$bmc_reset\" \"$flag\" \"$delay\" \"$mode\" \"$wait\" \"$port\" \"$server_ip\" \"$LOOP\" \"$acserverport\" \"$safe\" \"$sysStaticIP\" \"$blackBoxStaticIP\" \"$runtime\" \"$filename\" \"$fs_type\" \"$disk_mode\" \"$specified_disk\" \"$remote\" \"$mix_io\" \"$log_interval\""
StandardInput=tty
StandardOutput=tty
StandardError=tty
TTYPath=/dev/tty3
TTYReset=yes
TTYVHangup=yes
UtmpIdentifier=tty3
Restart=no

[Install]
WantedBy=multi-user.target
EOF
            systemctl daemon-reload
            systemctl enable fio-test.service
            # Verification: Show the file was created and wait 10s so user can see it
            ls -l /etc/systemd/system/fio-test.service
            echo "--------- Service File Content ---------"
            cat /etc/systemd/system/fio-test.service
            echo "----------------------------------------"
            echo "Testing configuration written. System will reboot in 10 seconds..."
            sleep 10
            # Also ensure crontab is clear to avoid double starts
            crontab -l 2>/dev/null | grep -v "run_fio.sh" | crontab -
        else
            systemctl set-default multi-user.target
            sed -i 's#ExecStart=-/sbin/agetty --noclear %I#ExecStart=-/sbin/agetty --noclear --autologin root %I#' /usr/lib/systemd/system/getty@.service
            if [ -f "/etc/systemd/system/getty@tty1.service" ]; then
                sed -i 's#ExecStart=-/sbin/agetty --noclear %I#ExecStart=-/sbin/agetty --noclear --autologin root %I#' /etc/systemd/system/getty@tty1.service
            fi
            if [ -f "/etc/systemd/system/getty.target.wants/getty@tty1.service" ]; then
                sed -i 's#ExecStart=-/sbin/agetty --noclear %I#ExecStart=-/sbin/agetty --noclear --autologin root %I#' /etc/systemd/system/getty.target.wants/getty@tty1.service
            fi
        fi
    elif [[ $product_name == "S6410" ]]; then
        sed -i 's/id:5:initdefault:/id:3:initdefault:/' /etc/inittab
        sed -i 's#exec /sbin/mingetty#exec /sbin/mingetty --autologin root#' /etc/init/tty.conf
    elif [[ $system_CentOS6 == "1" ]]; then
        sed -i 's/id:5:initdefault:/id:3:initdefault:/' /etc/inittab
        sed -i 's#exec /sbin/mingetty#exec /sbin/mingetty --autologin root#' /etc/init/tty.conf
    elif [[ ${system_CentOS8} == "1" ]] || [[ ${system_ctyunos} == "1" ]] || [[ ${system_Redhat9} == "1" ]] || [[ ${system_Rocky9} -ne 0 ]];then
        ln -sf /usr/lib/systemd/system/multi-user.target /etc/systemd/system/default.target
        if [ -f "/etc/systemd/system/getty.target.wants/getty@tty1.service" ]; then
            rm -rf /etc/systemd/system/getty.target.wants/getty@tty1.service
            cp /usr/lib/systemd/system/getty@.service /usr/lib/systemd/system/getty@.service.bak
            sed -i "s#ExecStart=-/sbin/agetty .*#ExecStart=-/sbin/agetty -a root --noclear %I \$TERM#" /usr/lib/systemd/system/getty@.service
            ln -s /usr/lib/systemd/system/getty@.service /etc/systemd/system/getty.target.wants/getty@tty1.service
            systemctl daemon-reload
            systemctl enable getty@tty1.service
            systemctl start getty@tty1.service
        fi
    elif [[ $system_Debian == "1" ]]; then
        ln -sf /lib/systemd/system/multi-user.target /lib/systemd/system/default.target
        sed -i "s#ExecStart=.*#ExecStart=-/sbin/agetty --noclear --autologin root %I \$TERM#" /lib/systemd/system/getty@.service
	if [ -L /etc/systemd/system/getty.target.wants/getty@tty1.service ];then
		rm /etc/systemd/system/getty.target.wants/getty@tty1.service
	fi
	systemctl enable getty@tty1.service
    elif [[ $system_NFS == "1" ]] || [[ $system_NFS3 == "1" ]] || [[ ${system_UOS_Server} != "0" ]];then
	systemctl set-default multi-user.target
	sed -i 's#^.*ExecStart.*$#ExecStart=-/sbin/agetty --noclear --autologin root %I $TERM#' /usr/lib/systemd/system/getty@.service
	if [ -f "/etc/systemd/system/getty.target.wants/getty@tty1.service" ]; then
		sed -i 's#^.*ExecStart.*$#ExecStart=-/sbin/agetty --noclear --autologin root %I $TERM#' /etc/systemd/system/getty.target.wants/getty@tty1.service
	fi
	rm -rf /etc/systemd/system/getty.target.wants/getty@tty1.service
	ln -s /usr/lib/systemd/system/getty@.service /etc/systemd/system/getty.target.wants/getty@tty1.service

    elif [[ ${system_kylin} == "1" ]] && [[ ${system_Kylin} == "0" ]]; then
        #systemctl set-default multi-user.target
        #ln -sf /usr/lib/systemd/system/multi-user.target /etc/systemd/system/default.target
        sed -i 's#autologin-user=sugon#autologin-user=root#' /etc/lightdm/lightdm.conf
        sed -i 's#ExecStart=-/sbin/agetty --noclear %I#ExecStart=-/sbin/agetty --noclear --autologin root %I#' /usr/lib/systemd/system/getty@.service
        sed -i 's#ExecStart=-/sbin/agetty --noclear %I#ExecStart=-/sbin/agetty --noclear --autologin root %I#' /lib/systemd/system/getty@.service
        if [ -f "/etc/systemd/system/getty@tty1.service" ]; then
                sed -i 's#ExecStart=-/sbin/agetty --noclear %I#ExecStart=-/sbin/agetty --noclear --autologin root %I#' /etc/systemd/system/getty@tty1.service
        fi
        if [ -f "/etc/systemd/system/getty.target.wants/getty@tty1.service" ]; then
                sed -i 's#ExecStart=-/sbin/agetty --noclear %I#ExecStart=-/sbin/agetty --noclear --autologin root %I#' /etc/systemd/system/getty.target.wants/getty@tty1.service
	    fi
        if [ -f "/usr/lib/systemd/system/serial-getty@.service " ]; then
               sed -i 's#ExecStart=-/sbin/agetty --keep-baud 115200,38400,9600 %I $TERM#ExecStart=-/sbin/agetty --keep-baud 115200,38400,9600 %I $TERM --autologin root %I#' /usr/lib/systemd/system/serial-getty@.service

        fi

    #适配新版麒麟系统区别于旧版麒麟系统。
    elif [[ ${system_Kylin} != "0" ]]; then
        if [[ ${system_Kylin_Debian} -eq 0 ]];then
            ln -sf /usr/lib/systemd/system/multi-user.target /etc/systemd/system/default.target
        fi
        sed -i 's#ExecStart=.*#ExecStart=-/sbin/agetty --noclear --autologin root %I#' /usr/lib/systemd/system/getty@.service
        #sed -i 's#ExecStart=.*#ExecStart=-/sbin/agetty --noclear --autologin root %I#' /lib/systemd/system/getty@.service
        #sed -i 's#ExecStart=.*#ExecStart=-/sbin/agetty --noclear --autologin root %I#' /etc/systemd/system/getty.target.wants/getty@tty1.service
        rm -rf /etc/systemd/system/getty.target.wants/getty@tty1.service
        ln -s /usr/lib/systemd/system/getty@.service /etc/systemd/system/getty.target.wants/getty@tty1.service

    fi
}

function autoopen()
{
    show_produce_message "autoopen"
	if [[ "$system_SUSE" -eq 1 ]];then
	    echo "cd $CP_ROOT_DIR" >> /etc/bash.bashrc
        echo "sh $CP_ROOT_DIR/run_fio.sh \"$item\" \"$check\" \"$bmc_reset\" \"$flag\" \"$delay\" \"$mode\" \"$wait\" \"$port\" \"$server_ip\" \"$LOOP\" \"$acserverport\" \"$safe\" \"$sysStaticIP\" \"$blackBoxStaticIP\" \"$runtime\" \"$filename\" \"$fs_type\" \"$disk_mode\" \"$specified_disk\" \"$remote\" \"$mix_io\" \"$log_interval\"" >> /etc/bash.bashrc
    elif [[ $System_Sugon == 1 ]] || [[ $System_NFS_PC5 != 0 ]];then
	cd ~
        echo "temp=\`tty |grep tty1 |wc -l\`" >> /root/.profile
        echo "if [[ \"\$temp\" -eq 1 ]];then" >> /root/.profile
        echo "cd $Cur_Dir" >> /root/.profile
        echo "sh $CP_ROOT_DIR/run_fio.sh \"$item\" \"$check\" \"$bmc_reset\" \"$flag\" \"$delay\" \"$mode\" \"$wait\" \"$port\" \"$server_ip\" \"$LOOP\" \"$acserverport\" \"$safe\" \"$sysStaticIP\" \"$blackBoxStaticIP\" \"$runtime\" \"$filename\" \"$fs_type\" \"$disk_mode\" \"$specified_disk\" \"$remote\" \"$mix_io\" \"$log_interval\"" >> /root/.profile
        echo "fi" >> /root/.profile
	cat /root/.profile
	cd - >/dev/null
    elif [[ "$system_Redhat" -eq 1 ]] || [[ "$system_CentOS" -eq 1 ]] || [[ "$system_Redhat7" -eq 1 ]] || [[ "$system_CentOS8" -eq 1 ]] || [[ "$system_NFS" -eq 1 ]] || [[ $system_NFS3 -ne 0 ]] || [[ "${system_Kylin}" -ne 0 ]] || [[ "${system_kylin}" -ne 0 ]] || [[ ${system_Redhat9} -eq 1 ]] || [[ ${system_ctyunos} -eq 1 ]] || [[ ${system_UOS_Server} -ne 0  ]] || [[ ${system_Rocky9} -ne 0 ]];then
        echo "temp=\`tty |grep tty1 |wc -l\`" >> /root/.bash_profile
        echo "if [[ \"\$temp\" -eq 1 ]];then" >> /root/.bash_profile
        echo "cd $CP_ROOT_DIR" >> /root/.bash_profile
        echo "sh $CP_ROOT_DIR/run_fio.sh \"$item\" \"$check\" \"$bmc_reset\" \"$flag\" \"$delay\" \"$mode\" \"$wait\" \"$port\" \"$server_ip\" \"$LOOP\" \"$acserverport\" \"$safe\" \"$sysStaticIP\" \"$blackBoxStaticIP\" \"$runtime\" \"$filename\" \"$fs_type\" \"$disk_mode\" \"$specified_disk\" \"$remote\" \"$mix_io\" \"$log_interval\"" >> /root/.bash_profile
        echo "fi" >> /root/.bash_profile
    elif [ -f /etc/os-release ] && grep -iq "Ubuntu" /etc/os-release ;then
        # Systemd handles auto-open for Ubuntu, no need to modify .profile
        show_produce_message "Ubuntu: Skipping .profile modification (using Systemd)"
    elif [[ "$system_Debian" -eq 1 ]];then
        echo 'temp=`tty |grep tty1 |wc -l`' >> /root/.bash_profile
        echo 'if [ $temp -eq 1 ];then' >> /root/.bash_profile
        echo "cd $CP_ROOT_DIR" >> /root/.bash_profile
        echo "sh $CP_ROOT_DIR/run_fio.sh \"$item\" \"$check\" \"$bmc_reset\" \"$flag\" \"$delay\" \"$mode\" \"$wait\" \"$port\" \"$server_ip\" \"$LOOP\" \"$acserverport\" \"$safe\" \"$sysStaticIP\" \"$blackBoxStaticIP\" \"$runtime\" \"$filename\" \"$fs_type\" \"$disk_mode\" \"$specified_disk\" \"$remote\" \"$mix_io\" \"$log_interval\"" >> /root/.bash_profile
        echo "fi" >> /root/.bash_profile
    fi
}

function backup()
{
    show_produce_message "backup files"
    [ -f /etc/bash.bashrc ] && cp /etc/bash.bashrc /etc/bash.bashrc.bak
    [ -f /etc/inittab ] && cp /etc/inittab /etc/inittab.bak
    [ -f /etc/init/tty.conf ] && cp /etc/init/tty.conf /etc/init/tty.conf.bak
    [ -f /root/.bash_profile ] && cp /root/.bash_profile /root/.bash_profile.bak
    [ -f /root/.profile ] && cp /root/.profile /root/.profile.bak
}

function flush_cache() {
    sync
    echo 3 > /proc/sys/vm/drop_caches
}

function restore()
{
    show_produce_message "Restore environment & Kill running processes"
    
    # 1. Kill any running FIO and test script processes
    echo "- Killing running FIO and script processes..."
    pkill -9 fio >/dev/null 2>&1
    pkill -9 -f run_fio.sh >/dev/null 2>&1
    pkill -9 -f powercycle_direct.sh >/dev/null 2>&1
    # 排除当前 restore 进程自身(经由 Fio_All.sh 启动)，避免自杀导致后续环境恢复中断
    for pid in $(pgrep -f Fio_All.sh 2>/dev/null); do
        [ "$pid" = "$$" ] && continue
        [ "$pid" = "$PPID" ] && continue
        kill -9 "$pid" >/dev/null 2>&1
    done
    pkill -9 -f nvme_raid_test.py >/dev/null 2>&1
    
    # 2. Restore system config files
    echo "- Restoring system configuration files..."
    local files=("/etc/bash.bashrc" "/etc/inittab" "/etc/init/tty.conf" "/root/.bash_profile" "/root/.profile")
    for file in "${files[@]}"; do
        if [ -f "${file}.bak" ]; then
            rm -f "$file"
            cp -f "${file}.bak" "$file"
            rm -f "${file}.bak"
        fi
    done

    # 3. Cleanup systemd service if it was used for reboot tests
    if [ -f /etc/os-release ] && grep -iq "Ubuntu" /etc/os-release ; then
        echo "- Cleaning up systemd services..."
        systemctl disable fio-test.service >/dev/null 2>&1
        rm -f /etc/systemd/system/fio-test.service
        systemctl unmask getty@tty3.service >/dev/null 2>&1
        systemctl start getty@tty3.service >/dev/null 2>&1
        systemctl daemon-reload
        # Also clean crontab
        crontab -l 2>/dev/null | grep -v "run_fio.sh" | crontab -
    fi
    echo "- Cleanup complete."
}



