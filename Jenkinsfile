def targetIPs = []
def kernelDriverCommit = ''
def kernelDriverFullCommit = ''
def kernelDriverRef = ''
def kernelDriverMrIid = ''
def kernelDriverMrTitle = ''
def kernelDriverMrUpdatedAt = ''
def kernelDriverMrUrl = ''
def raidCliCommit = ''
def raidCliFullCommit = ''
def raidCliDpraidPath = ''
def triggerSource = ''
def shouldRunTests = false
def useQemuVmTarget = false
def automaticMrTriggered = false

def copyWorkspaceToRemote(ip, remoteDir, targetUser, sshOpts) {
    sh """
    tar \
      --exclude='./.git' \
      --exclude='./kernel_driver/.git' \
      --exclude='./raid_cli' \
      --exclude='./.pytest_cache' \
      --exclude='./__pycache__' \
      --exclude='./allure-results' \
      --exclude='./report.xml' \
      --exclude='./report_*.xml' \
      --exclude='./test_execution_*.log' \
      --exclude='./feishu_payload.json' \
      -czf - . | ssh ${sshOpts} ${targetUser}@${ip} 'tar -xzf - -C ${remoteDir}'
    """
}

pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        skipDefaultCheckout()
    }

    triggers {
        cron('* * * * *')
    }

    parameters {
        booleanParam(
            name: 'RESTORE',
            defaultValue: false,
            description: 'Only stop and clean up running test processes on target nodes. Do not run tests in this build.'
        )
        booleanParam(
            name: 'DEBUG_NO_FEISHU',
            defaultValue: false,
            description: 'Debug mode: run the same pipeline but skip Feishu notification.'
        )
        booleanParam(
            name: 'SIMULATE_AUTO_MR_TRIGGER',
            defaultValue: false,
            description: 'Debug mode: manual build uses the same QEMU VM target path as automatic MR trigger.'
        )
        string(
            name: 'MANUAL_MR_IID',
            defaultValue: '',
            trim: true,
            description: 'Manual rerun: set a kernel_driver merge request IID, for example 141. Empty means run main branch.'
        )
    }

    environment {
        FEISHU_WEBHOOK = credentials('feishu-webhook')
        TARGET_USER = 'root'
        ALLOW_DESTRUCTIVE_FIO = '1'
        TARGET_NODE_TIMEOUT_MINUTES = '90'
        SSH_OPTS = '-o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ConnectTimeout=15'
        QEMU_VM_SSH_PORT = '2233'
        QEMU_VM_SCP_PORT = '2233'
        QEMU_VM_PASSWORD = '1'
        QEMU_VM_WORKDIR = '/root/gr/qemu'
        QEMU_VM_START_SCRIPT = './start_vm.sh'
        QEMU_KERNEL_BUILD_DIR = '/root/gr/qemu/general_kernel'
        QEMU_VFIO_BIND_SCRIPT = './vfio-bind.sh'

        KERNEL_DRIVER_REPO = 'git@192.168.21.185:raid_max/kernel_driver.git'
        KERNEL_DRIVER_BRANCH = 'main'
        KERNEL_DRIVER_CRED = 'kernel_driver_ssh'
        KERNEL_DRIVER_GITLAB_API = 'http://192.168.21.185:8081/api/v4'
        KERNEL_DRIVER_GITLAB_PROJECT = 'raid_max%2Fkernel_driver'
        KERNEL_DRIVER_GITLAB_TOKEN_CRED = 'kernel_driver_gitlab_token'
        RAID_CLI_REPO = 'git@192.168.21.185:general_tools/raid_cli.git'
        RAID_CLI_BRANCH = 'hostraid_cli'
        RAID_CLI_CRED = 'kernel_driver_ssh'
    }

    stages {
        stage('Prepare Workspace') {
            steps {
                cleanWs()

                checkout scm: scm, poll: false, changelog: false

                script {
                    def jenkinsHome = env.JENKINS_HOME ?: '/var/lib/jenkins'

                    if (!params.RESTORE) {
                        def manuallyTriggered = currentBuild.getBuildCauses('hudson.model.Cause$UserIdCause').size() > 0
                        def markerName = "${env.JOB_NAME}_kernel_driver_open_mrs".replaceAll('[^A-Za-z0-9_.-]', '_')
                        def markerPath = "${jenkinsHome}/.raid_nvme/${markerName}.signature"
                        def raidCliMarkerName = "${env.JOB_NAME}_${env.RAID_CLI_BRANCH}_raid_cli_commit".replaceAll('[^A-Za-z0-9_.-]', '_')
                        def raidCliMarkerPath = "${jenkinsHome}/.raid_nvme/${raidCliMarkerName}.commit"
                        def raidCliCheckPath = "${jenkinsHome}/.raid_nvme/${raidCliMarkerName}.last_check"
                        def raidCliWorkDir = "${jenkinsHome}/.raid_nvme/${raidCliMarkerName}.repo"
                        raidCliDpraidPath = "${raidCliWorkDir}/dpraid"
                        def mrProps = [:]
                        def currentMrSignature = 'none'
                        def hasNewOpenMrEvent = false
                        def hasRaidCliUpdate = false
                        def syncRaidCli = { String reason ->
                            echo "Check raid_cli(${env.RAID_CLI_BRANCH}) updates: ${reason}."
                            checkout scm: [
                                $class: 'GitSCM',
                                branches: [[name: "*/${env.RAID_CLI_BRANCH}"]],
                                userRemoteConfigs: [[
                                    url: env.RAID_CLI_REPO,
                                    credentialsId: env.RAID_CLI_CRED
                                ]],
                                extensions: [
                                    [$class: 'RelativeTargetDirectory', relativeTargetDir: 'raid_cli'],
                                    [$class: 'CloneOption', shallow: true, depth: 50, noTags: true, timeout: 30]
                                ]
                            ], poll: false, changelog: false

                            raidCliFullCommit = sh(
                                script: "git -C raid_cli rev-parse HEAD 2>/dev/null || echo unknown",
                                returnStdout: true
                            ).trim()
                            raidCliCommit = sh(
                                script: "git -C raid_cli rev-parse --short HEAD 2>/dev/null || echo unknown",
                                returnStdout: true
                            ).trim()

                            def previousRaidCliCommit = sh(
                                script: "cat '${raidCliMarkerPath}' 2>/dev/null || true",
                                returnStdout: true
                            ).trim()
                            def persistentRaidCliMissing = sh(
                                script: "test -d '${raidCliWorkDir}/.git' && test -x '${raidCliDpraidPath}'; echo \$?",
                                returnStdout: true
                            ).trim() != '0'
                            def needsRaidCliUpdate = raidCliFullCommit != 'unknown' && (previousRaidCliCommit != raidCliFullCommit || persistentRaidCliMissing)

                            if (needsRaidCliUpdate) {
                                sh """
                                set -eu
                                mkdir -p '${jenkinsHome}/.raid_nvme'
                                rm -rf '${raidCliWorkDir}.next'
                                cp -a raid_cli '${raidCliWorkDir}.next'
                                rm -rf '${raidCliWorkDir}'
                                mv '${raidCliWorkDir}.next' '${raidCliWorkDir}'
                                cd '${raidCliWorkDir}'
                                chmod +x ./build.sh
                                ./build.sh
                                test -x ./dpraid
                                printf '%s\\n' '${raidCliFullCommit}' > '${raidCliMarkerPath}'
                                """
                                currentBuild.description = "raid_cli ${raidCliCommit}"
                                echo "raid_cli(${env.RAID_CLI_BRANCH}) updated and built on Jenkins server: ${previousRaidCliCommit ?: 'none'} -> ${raidCliFullCommit}"
                                echo "raid_cli checkout path: ${raidCliWorkDir}"
                                echo "dpraid artifact path: ${raidCliDpraidPath}"
                            } else {
                                echo "raid_cli(${env.RAID_CLI_BRANCH}) has no new commit: ${raidCliCommit}"
                            }

                            return needsRaidCliUpdate
                        }

                        if (manuallyTriggered) {
                            def manualMrIid = (params.MANUAL_MR_IID ?: '').trim()
                            shouldRunTests = true
                            useQemuVmTarget = params.SIMULATE_AUTO_MR_TRIGGER
                            automaticMrTriggered = params.SIMULATE_AUTO_MR_TRIGGER
                            def raidCliBootstrapMissing = sh(
                                script: "test -d '${raidCliWorkDir}/.git' && test -x '${raidCliDpraidPath}'; echo \$?",
                                returnStdout: true
                            ).trim() != '0'
                            if (raidCliBootstrapMissing) {
                                hasRaidCliUpdate = syncRaidCli('initial bootstrap is missing')
                            }

                            if (manualMrIid) {
                                if (!(manualMrIid ==~ /^[0-9]+$/)) {
                                    error "MANUAL_MR_IID must be a numeric GitLab merge request IID, got: ${manualMrIid}"
                                }

                                withCredentials([string(credentialsId: env.KERNEL_DRIVER_GITLAB_TOKEN_CRED, variable: 'GITLAB_TOKEN')]) {
                                    sh """
                                    set -eu
                                    curl -fsS \\
                                      --header "PRIVATE-TOKEN: \${GITLAB_TOKEN}" \\
                                      "${KERNEL_DRIVER_GITLAB_API}/projects/${KERNEL_DRIVER_GITLAB_PROJECT}/merge_requests/${manualMrIid}" \\
                                      -o kernel_driver_manual_mr.json

                                    python3 - <<'PY' > kernel_driver_manual_mr.properties
import json

with open('kernel_driver_manual_mr.json', encoding='utf-8') as fh:
    mr = json.load(fh)

def prop_value(value):
    return str(value or '').replace('\\n', ' ').replace('\\r', ' ')

print(f"MR_IID={prop_value(mr.get('iid'))}")
print(f"MR_TITLE={prop_value(mr.get('title'))}")
print(f"MR_SOURCE_BRANCH={prop_value(mr.get('source_branch'))}")
print(f"MR_TARGET_BRANCH={prop_value(mr.get('target_branch'))}")
print(f"MR_SHA={prop_value(mr.get('sha'))}")
print(f"MR_UPDATED_AT={prop_value(mr.get('updated_at'))}")
print(f"MR_WEB_URL={prop_value(mr.get('web_url'))}")
PY
                                    """
                                }

                                readFile('kernel_driver_manual_mr.properties').split('\\r?\\n').each { line ->
                                    if (line.contains('=')) {
                                        def parts = line.split('=', 2)
                                        mrProps[parts[0]] = parts[1]
                                    }
                                }

                                kernelDriverRef = mrProps.MR_SOURCE_BRANCH ?: env.KERNEL_DRIVER_BRANCH
                                kernelDriverMrIid = mrProps.MR_IID ?: manualMrIid
                                kernelDriverMrTitle = mrProps.MR_TITLE ?: ''
                                kernelDriverMrUpdatedAt = mrProps.MR_UPDATED_AT ?: ''
                                kernelDriverMrUrl = mrProps.MR_WEB_URL ?: ''
                                triggerSource = params.SIMULATE_AUTO_MR_TRIGGER ? 'Manual MR Build (Simulate Auto MR)' : 'Manual MR Build'
                                echo "Manual MR build requested. Run smoke tests on kernel_driver !${kernelDriverMrIid} ${kernelDriverRef}."
                            } else {
                                kernelDriverRef = env.KERNEL_DRIVER_BRANCH
                                triggerSource = params.SIMULATE_AUTO_MR_TRIGGER ? 'Manual Build (Simulate Auto MR)' : 'Manual Build'
                                echo "Manual build requested. Run smoke tests on kernel_driver/${kernelDriverRef}."
                            }
                            if (params.SIMULATE_AUTO_MR_TRIGGER) {
                                echo 'SIMULATE_AUTO_MR_TRIGGER=true, use QEMU VM target path for this manual build.'
                            }
                        } else {
                            def nowEpoch = sh(script: 'date +%s', returnStdout: true).trim().toLong()
                            def lastRaidCliCheck = sh(
                                script: "cat '${raidCliCheckPath}' 2>/dev/null || echo 0",
                                returnStdout: true
                            ).trim()
                            def lastRaidCliEpoch = (lastRaidCliCheck ==~ /^[0-9]+$/) ? lastRaidCliCheck.toLong() : 0L

                            def raidCliBootstrapMissing = sh(
                                script: "test -d '${raidCliWorkDir}/.git' && test -x '${raidCliDpraidPath}'; echo \$?",
                                returnStdout: true
                            ).trim() != '0'

                            if (raidCliBootstrapMissing || nowEpoch - lastRaidCliEpoch >= 1800L) {
                                def reason = raidCliBootstrapMissing ? 'initial bootstrap is missing' : '30-minute interval'
                                hasRaidCliUpdate = syncRaidCli(reason)
                                sh """
                                mkdir -p '${jenkinsHome}/.raid_nvme'
                                printf '%s\\n' '${nowEpoch}' > '${raidCliCheckPath}'
                                """
                            } else {
                                echo "Skip raid_cli polling. Last check was ${nowEpoch - lastRaidCliEpoch}s ago."
                            }

                            withCredentials([string(credentialsId: env.KERNEL_DRIVER_GITLAB_TOKEN_CRED, variable: 'GITLAB_TOKEN')]) {
                                sh '''
                                set -eu
                                curl -fsS \
                                  --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
                                  "${KERNEL_DRIVER_GITLAB_API}/projects/${KERNEL_DRIVER_GITLAB_PROJECT}/merge_requests?state=opened&order_by=updated_at&sort=desc&per_page=100" \
                                  -o kernel_driver_mrs.json

                                python3 - <<'PY' > kernel_driver_mr.properties
import json

with open('kernel_driver_mrs.json', encoding='utf-8') as fh:
    merge_requests = json.load(fh)

merge_requests = [
    mr for mr in merge_requests
    if not str(mr.get('title') or '').strip().lower().startswith('[wip]')
]

def prop_value(value):
    return str(value or '').replace('\\n', ' ').replace('\\r', ' ')

if not merge_requests:
    print('MR_COUNT=0')
    print('MR_SIGNATURE=none')
else:
    signature_parts = [
        f"{mr.get('iid')}:{mr.get('sha')}"
        for mr in sorted(merge_requests, key=lambda item: item.get('iid') or 0)
    ]
    latest = merge_requests[0]
    print(f"MR_COUNT={len(merge_requests)}")
    print(f"MR_SIGNATURE={prop_value('|'.join(signature_parts))}")
    print(f"MR_IID={prop_value(latest.get('iid'))}")
    print(f"MR_TITLE={prop_value(latest.get('title'))}")
    print(f"MR_SOURCE_BRANCH={prop_value(latest.get('source_branch'))}")
    print(f"MR_TARGET_BRANCH={prop_value(latest.get('target_branch'))}")
    print(f"MR_SHA={prop_value(latest.get('sha'))}")
    print(f"MR_UPDATED_AT={prop_value(latest.get('updated_at'))}")
    print(f"MR_WEB_URL={prop_value(latest.get('web_url'))}")
PY
                                '''
                            }

                            readFile('kernel_driver_mr.properties').split('\\r?\\n').each { line ->
                                if (line.contains('=')) {
                                    def parts = line.split('=', 2)
                                    mrProps[parts[0]] = parts[1]
                                }
                            }

                            def mrCount = (mrProps.MR_COUNT ?: '0').toInteger()
                            currentMrSignature = mrProps.MR_SIGNATURE ?: 'none'
                            def previousMrSignature = sh(
                                script: "cat '${markerPath}' 2>/dev/null || true",
                                returnStdout: true
                            ).trim()

                            def currentSignatures = currentMrSignature == 'none' ? [] : currentMrSignature.split('\\|') as List
                            def previousSignatures = previousMrSignature ? previousMrSignature.split('\\|') as List : []
                            previousSignatures = previousSignatures.collect { signature ->
                                def parts = signature.split(':')
                                parts.size() >= 3 ? "${parts[0]}:${parts[-1]}" : signature
                            }
                            def previousSignatureSet = previousSignatures as Set
                            hasNewOpenMrEvent = currentSignatures.any { !previousSignatureSet.contains(it) }

                            if (!hasNewOpenMrEvent) {
                                if (hasRaidCliUpdate) {
                                    echo "raid_cli was updated for the test environment. No kernel_driver MR event, so skip smoke tests."
                                    return
                                }
                                currentBuild.result = 'NOT_BUILT'
                                echo "kernel_driver open merge requests have no new event. Skip NVMe RAID smoke tests."
                                return
                            }

                            kernelDriverRef = mrProps.MR_SOURCE_BRANCH ?: env.KERNEL_DRIVER_BRANCH
                            kernelDriverMrIid = mrProps.MR_IID ?: ''
                            kernelDriverMrTitle = mrProps.MR_TITLE ?: ''
                            kernelDriverMrUpdatedAt = mrProps.MR_UPDATED_AT ?: ''
                            kernelDriverMrUrl = mrProps.MR_WEB_URL ?: ''

                            shouldRunTests = true
                            useQemuVmTarget = true
                            automaticMrTriggered = true
                            triggerSource = 'kernel_driver Merge Request'

                            if (kernelDriverMrIid) {
                                echo "kernel_driver open MR !${kernelDriverMrIid} updated at ${kernelDriverMrUpdatedAt}: ${kernelDriverMrTitle}"
                            } else {
                                echo "GitLab MR polling has no MR IID. Fall back to ${kernelDriverRef}."
                            }
                        }

                        checkout scm: [
                            $class: 'GitSCM',
                            branches: [[name: "*/${kernelDriverRef}"]],
                            userRemoteConfigs: [[
                                url: env.KERNEL_DRIVER_REPO,
                                credentialsId: env.KERNEL_DRIVER_CRED
                            ]],
                            extensions: [
                                [$class: 'RelativeTargetDirectory', relativeTargetDir: 'kernel_driver'],
                                [$class: 'CloneOption', shallow: true, depth: 50, noTags: true, timeout: 30]
                            ]
                        ], poll: false, changelog: false

                        def mrSha = mrProps.MR_SHA ?: ''
                        if (mrSha ==~ /^[0-9a-f]{40}$/) {
                            sh "git -C kernel_driver checkout --detach '${mrSha}'"
                        }

                        kernelDriverFullCommit = sh(
                            script: "git -C kernel_driver rev-parse HEAD 2>/dev/null || echo unknown",
                            returnStdout: true
                        ).trim()
                        kernelDriverCommit = sh(
                            script: "git -C kernel_driver rev-parse --short HEAD 2>/dev/null || echo unknown",
                            returnStdout: true
                        ).trim()
                        echo "kernel_driver(${kernelDriverRef}) commit: ${kernelDriverCommit}"

                        if (currentMrSignature != 'none') {
                            sh """
                            mkdir -p '${jenkinsHome}/.raid_nvme'
                            printf '%s\\n' '${currentMrSignature}' > '${markerPath}'
                            """
                        }
                    }
                }

                script {
                    if (!shouldRunTests && !params.RESTORE) {
                        echo 'Skip target node loading because kernel_driver merge requests have no new event.'
                        return
                    }

                    if (!fileExists('target_ips.txt')) {
                        error 'Missing target_ips.txt in repository root.'
                    }

                    def ipContent = readFile('target_ips.txt').trim()
                    targetIPs = ipContent.split('\\r?\\n').findAll { it.trim() != '' && !it.startsWith('#') }

                    if (targetIPs.size() == 0) {
                        error 'No valid target IPs found in target_ips.txt.'
                    }

                    echo "Target nodes: ${targetIPs}"
                }
            }
        }

        stage('Kernel Driver Placeholder') {
            when { expression { return !params.RESTORE && shouldRunTests } }
            steps {
                script {
                    echo "kernel_driver commit for this run: ${kernelDriverCommit ?: 'unknown'}"
                    if (kernelDriverMrIid) {
                        echo "kernel_driver MR for this run: !${kernelDriverMrIid} ${kernelDriverMrUrl}"
                    }
                    echo 'This stage is still a placeholder. kernel_driver is only checked out and its commit is displayed.'
                }
            }
        }

        stage('Restore Targets') {
            when { expression { return params.RESTORE } }
            steps {
                script {
                    def restoreTasks = [:]

                    for (int i = 0; i < targetIPs.size(); i++) {
                        def ip = targetIPs[i]

                        restoreTasks["Restore_${ip}"] = {
                            stage("Restore on ${ip}") {
                                def remoteDir = "/root/Cyril/Jenkins/jenkins_nvme_restore_${env.BUILD_NUMBER}"

                                echo "[${ip}] stop running test processes"
                                sh """
                                ssh ${env.SSH_OPTS} ${env.TARGET_USER}@${ip} '
                                    pkill -9 -f nvme_raid_test.py 2>/dev/null || true
                                    pkill -2 -f Stress_Monitor/main.py 2>/dev/null || true
                                    pkill -9 -f run_fio.sh 2>/dev/null || true
                                    pkill -9 -f Fio_All.sh 2>/dev/null || true
                                    pkill -9 fio 2>/dev/null || true
                                ' || true
                                """

                                echo "[${ip}] deploy restore scripts"
                                sh "ssh ${env.SSH_OPTS} ${env.TARGET_USER}@${ip} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'"
                                copyWorkspaceToRemote(ip, remoteDir, env.TARGET_USER, env.SSH_OPTS)

                                echo "[${ip}] execute restore"
                                sh """
                                ssh ${env.SSH_OPTS} ${env.TARGET_USER}@${ip} '
                                    cd ${remoteDir}/IO_Stress && bash ./Fio_All.sh -i restore || true
                                '
                                """

                                echo "[${ip}] clean temporary directory"
                                sh "ssh ${env.SSH_OPTS} ${env.TARGET_USER}@${ip} 'rm -rf ${remoteDir}' || true"
                            }
                        }
                    }

                    parallel restoreTasks
                }
            }
        }

        stage('Run Tests') {
            when { expression { return !params.RESTORE && shouldRunTests } }
            steps {
                script {
                    def jenkinsHome = env.JENKINS_HOME ?: '/var/lib/jenkins'
                    def raidCliMarkerName = "${env.JOB_NAME}_${env.RAID_CLI_BRANCH}_raid_cli_commit".replaceAll('[^A-Za-z0-9_.-]', '_')
                    def raidCliRepoPathForRun = "${jenkinsHome}/.raid_nvme/${raidCliMarkerName}.repo"
                    def raidCliDpraidPathForRun = raidCliDpraidPath ?: "${raidCliRepoPathForRun}/dpraid"

                    sh "test -x '${raidCliDpraidPathForRun}'"
                    raidCliFullCommit = sh(
                        script: "git -C '${raidCliRepoPathForRun}' rev-parse HEAD 2>/dev/null || echo unknown",
                        returnStdout: true
                    ).trim()
                    raidCliCommit = sh(
                        script: "git -C '${raidCliRepoPathForRun}' rev-parse --short HEAD 2>/dev/null || echo unknown",
                        returnStdout: true
                    ).trim()
                    echo "Use dpraid artifact: ${raidCliDpraidPathForRun}"
                    echo "Use raid_cli(${env.RAID_CLI_BRANCH}) commit: ${raidCliCommit}"

                    def parallelTasks = [:]

                    for (int i = 0; i < targetIPs.size(); i++) {
                        def ip = targetIPs[i]

                        parallelTasks["Node_${ip}"] = {
                            stage("Test on ${ip}") {
                                def remoteDir = "/root/Cyril/Jenkins/jenkins_nvme_${env.BUILD_NUMBER}"
                                def envPrepareLog = "environment_prepare_${ip}.log"
                                def qemuVmForNode = useQemuVmTarget
                                def targetSsh = qemuVmForNode ?
                                    "sshpass -p '${env.QEMU_VM_PASSWORD}' ssh ${env.SSH_OPTS} -p ${env.QEMU_VM_SSH_PORT} ${env.TARGET_USER}@${ip}" :
                                    "ssh ${env.SSH_OPTS} ${env.TARGET_USER}@${ip}"
                                def targetScp = qemuVmForNode ?
                                    "sshpass -p '${env.QEMU_VM_PASSWORD}' scp ${env.SSH_OPTS} -P ${env.QEMU_VM_SCP_PORT}" :
                                    "scp ${env.SSH_OPTS}"
                                def qemuEnv = qemuVmForNode ? '1' : '0'

                                writeFile file: envPrepareLog, text: "[${ip}] Environment_Prepare started\n"

                                if (qemuVmForNode) {
                                    echo "[${ip}] start QEMU VM for automatic MR test"
                                    def qemuStatus = sh(
                                        returnStatus: true,
                                        script: """#!/bin/bash
set -o pipefail
{
echo "[${ip}] start QEMU VM for automatic MR test"
if ! command -v sshpass >/dev/null 2>&1; then
    echo "[${ip}] sshpass is missing on Jenkins server, try to install it automatically."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get -o DPkg::Lock::Timeout=600 update
        sudo apt-get -o DPkg::Lock::Timeout=600 install -y sshpass
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y sshpass
    elif command -v yum >/dev/null 2>&1; then
        sudo yum install -y sshpass
    elif command -v zypper >/dev/null 2>&1; then
        sudo zypper install -y sshpass
    fi
fi
command -v sshpass >/dev/null 2>&1 || { echo "sshpass is required on Jenkins server for QEMU VM login, and automatic install failed"; exit 1; }
if ${targetSsh} 'echo qemu vm already running' >/dev/null 2>&1; then
    echo "[${ip}] QEMU VM is already running, skip vfio bind and ${env.QEMU_VM_START_SCRIPT}"
else
    timeout --kill-after=60s 10m ssh ${env.SSH_OPTS} ${env.TARGET_USER}@${ip} '
    set -eu
    cd ${env.QEMU_VM_WORKDIR}
    test -x ${env.QEMU_VFIO_BIND_SCRIPT} || {
        echo "QEMU vfio bind script not found or not executable: ${env.QEMU_VM_WORKDIR}/${env.QEMU_VFIO_BIND_SCRIPT}" >&2
        exit 1
    }
    protected_names=\$(
        {
            findmnt -nvo SOURCE / /boot /boot/efi 2>/dev/null || true
            lsblk -nP -o NAME,PKNAME,MOUNTPOINT 2>/dev/null |
                awk -F'"'"'"'"'"' '"'"'\$6 != "" { print "/dev/" \$2; if (\$4 != "") print "/dev/" \$4 }'"'"'"'"'"'
        } |
        while read -r source; do
            [ -n "\$source" ] || continue
            source="\${source#/dev/}"
            printf "%s\\n" "\$source"
            pk=\$(lsblk -npo PKNAME "/dev/\$source" 2>/dev/null | sed "s#^/dev/##" || true)
            [ -n "\$pk" ] && printf "%s\\n" "\$pk"
        done | sort -u
    )
    vfio_devices=""
    for ctrl_path in /sys/class/nvme/nvme*; do
        [ -e "\$ctrl_path" ] || continue
        ctrl=\$(basename "\$ctrl_path")
        bdf=\$(basename "\$(readlink -f "\$ctrl_path/device")")
        skip=0
        for ns_path in "\$ctrl_path"/nvme*n*; do
            [ -e "\$ns_path" ] || continue
            ns=\$(basename "\$ns_path")
            pk=\$(lsblk -npo PKNAME "/dev/\$ns" 2>/dev/null | sed "s#^/dev/##" || true)
            for protected in \$protected_names; do
                if [ "\$ns" = "\$protected" ] || [ "\$pk" = "\$protected" ] || [ "\$ctrl" = "\$protected" ]; then
                    skip=1
                fi
            done
        done
        if [ "\$skip" = "1" ]; then
            echo "[${ip}] keep system NVMe on host: \$ctrl \$bdf"
            continue
        fi
        vfio_devices="\${vfio_devices} \${bdf}"
    done
    if [ -z "\$(printf "%s" "\$vfio_devices" | tr -d " ")" ]; then
        echo "[${ip}] no non-system NVMe PCI devices found for QEMU vfio bind"
        : > .jenkins_nvme_${env.BUILD_NUMBER}_vfio_devices
    else
        printf "%s\\n" \$vfio_devices > .jenkins_nvme_${env.BUILD_NUMBER}_vfio_devices
        for dev in \$vfio_devices; do
            echo "[${ip}] bind NVMe PCI device to QEMU vfio: \$dev"
            DEV="\$dev" ${env.QEMU_VFIO_BIND_SCRIPT} bind
        done
    fi
'
    timeout --kill-after=60s 10m ssh ${env.SSH_OPTS} ${env.TARGET_USER}@${ip} '
        set -eu
        cd ${env.QEMU_VM_WORKDIR}
        ${env.QEMU_VM_START_SCRIPT}
    '
    echo "[${ip}] wait 60s for QEMU VM boot"
    sleep 60
fi
for attempt in \$(seq 1 24); do
    if ${targetSsh} 'echo qemu vm ssh ready' >/dev/null 2>&1; then
        echo "[${ip}] QEMU VM SSH is ready"
        exit 0
    fi
    echo "[${ip}] waiting for QEMU VM SSH, attempt \${attempt}/24"
    sleep 5
done
echo "[${ip}] QEMU VM SSH is not ready after wait" >&2
exit 1
} 2>&1 | tee -a ${envPrepareLog}
"""
                                    )
                                    if (qemuStatus != 0) {
                                        sh "printf '%s\\n' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${envPrepareLog}"
                                        error "[${ip}] QEMU VM startup failed with exit code ${qemuStatus}"
                                    }
                                }

                                echo "[${ip}] deploy workspace"
                                def deployStatus = sh(
                                    returnStatus: true,
                                    script: """#!/bin/bash
set -o pipefail
{
echo "[${ip}] deploy workspace"
${targetSsh} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'
tar \\
  --exclude='./.git' \\
  --exclude='./kernel_driver/.git' \\
  --exclude='./raid_cli' \\
  --exclude='./.pytest_cache' \\
  --exclude='./__pycache__' \\
  --exclude='./allure-results' \\
  --exclude='./report.xml' \\
  --exclude='./report_*.xml' \\
  --exclude='./test_execution_*.log' \\
  --exclude='./environment_prepare_*.log' \\
  --exclude='./feishu_payload.json' \\
  -czf - . | ${targetSsh} 'tar -xzf - -C ${remoteDir}'
} 2>&1 | tee -a ${envPrepareLog}
"""
                                )
                                if (deployStatus != 0) {
                                    sh "printf '%s\\n' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${envPrepareLog}"
                                    error "[${ip}] deploy workspace failed with exit code ${deployStatus}"
                                }

                                echo "[${ip}] install latest dpraid"
                                def dpraidStatus = sh(
                                    returnStatus: true,
                                    script: """#!/bin/bash
set -o pipefail
{
echo "[${ip}] install latest dpraid"
                                ${targetScp} '${raidCliDpraidPathForRun}' ${env.TARGET_USER}@${ip}:/tmp/dpraid_${env.BUILD_NUMBER}
                                ${targetSsh} '
                                    install -m 0755 /tmp/dpraid_${env.BUILD_NUMBER} /usr/bin/dpraid
                                    rm -f /tmp/dpraid_${env.BUILD_NUMBER}
                                    /usr/bin/dpraid --help >/dev/null 2>&1 || true
                                '
} 2>&1 | tee -a ${envPrepareLog}
"""
                                )
                                if (dpraidStatus != 0) {
                                    sh "printf '%s\\n' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${envPrepareLog}"
                                    error "[${ip}] install latest dpraid failed with exit code ${dpraidStatus}"
                                }

                                echo "[${ip}] build and reload draid kernel driver"
                                def driverStatus = sh(
                                    returnStatus: true,
                                    script: """#!/bin/bash
set -o pipefail
{
echo "[${ip}] build and reload draid kernel driver"
if [ "${qemuEnv}" = "1" ]; then
    host_build_dir="/tmp/draid_build_${env.BUILD_NUMBER}"
    host_module="/tmp/draid_${env.BUILD_NUMBER}.ko"
    local_module="draid_${ip}_${env.BUILD_NUMBER}.ko"

    ssh ${env.SSH_OPTS} ${env.TARGET_USER}@${ip} "
        set -eu
        test -d '${env.QEMU_KERNEL_BUILD_DIR}' || {
            echo 'QEMU kernel build dir not found: ${env.QEMU_KERNEL_BUILD_DIR}' >&2
            exit 1
        }
        test -f '${env.QEMU_KERNEL_BUILD_DIR}/Makefile' || {
            echo 'QEMU kernel build dir has no Makefile: ${env.QEMU_KERNEL_BUILD_DIR}' >&2
            exit 1
        }
        rm -rf '\${host_build_dir}'
        mkdir -p '\${host_build_dir}'
    "
    tar -czf - -C kernel_driver/drivers/draid . | ssh ${env.SSH_OPTS} ${env.TARGET_USER}@${ip} "tar -xzf - -C '\${host_build_dir}'"
    ssh ${env.SSH_OPTS} ${env.TARGET_USER}@${ip} "
        set -eu
        command -v make >/dev/null 2>&1 || { echo 'make is required on QEMU host for draid build' >&2; exit 1; }
        command -v gcc >/dev/null 2>&1 || { echo 'gcc is required on QEMU host for draid build' >&2; exit 1; }
        make -C '${env.QEMU_KERNEL_BUILD_DIR}' M='\${host_build_dir}' modules
        test -f '\${host_build_dir}/draid.ko'
        cp -f '\${host_build_dir}/draid.ko' '\${host_module}'
    "
    scp ${env.SSH_OPTS} ${env.TARGET_USER}@${ip}:"\${host_module}" "\${local_module}"
    ${targetScp} "\${local_module}" ${env.TARGET_USER}@${ip}:${remoteDir}/kernel_driver/drivers/draid/draid.ko
    rm -f "\${local_module}"
    ssh ${env.SSH_OPTS} ${env.TARGET_USER}@${ip} "rm -rf '\${host_build_dir}' '\${host_module}'" || true
    ${targetSsh} '
        set -eu
        cd ${remoteDir}/kernel_driver/drivers/draid
        test -f ./draid.ko
        module_name=\$(modinfo -F name ./draid.ko 2>/dev/null || true)
        module_name=\${module_name:-draid}
        echo "draid.ko module name: \${module_name}"
        for candidate in "\${module_name}" draid; do
            if [ -n "\${candidate}" ] && grep -q "^\${candidate} " /proc/modules; then
                rmmod "\${candidate}" || modprobe -r "\${candidate}"
            fi
        done
        for candidate in "\${module_name}" draid; do
            if [ -n "\${candidate}" ] && grep -q "^\${candidate} " /proc/modules; then
                echo "kernel module \${candidate} is still loaded after remove attempt" >&2
                grep -i draid /proc/modules >&2 || true
                exit 1
            fi
        done
        if ! insmod ./draid.ko; then
            echo "insmod ./draid.ko failed. Current related modules:" >&2
            grep -i draid /proc/modules >&2 || true
            exit 1
        fi
        grep -q "^\${module_name} " /proc/modules
    '
else
    ${targetSsh} '
                                    set -eu
                                    need_driver_deps=0
                                    for tool in make gcc insmod modinfo; do
                                        command -v "\${tool}" >/dev/null 2>&1 || need_driver_deps=1
                                    done
                                    [ -e "/lib/modules/\$(uname -r)/build" ] || need_driver_deps=1
                                    if [ "\${need_driver_deps}" = "1" ]; then
                                        if command -v apt-get >/dev/null 2>&1; then
                                            export DEBIAN_FRONTEND=noninteractive
                                            apt_retry() {
                                                for attempt in 1 2 3; do
                                                    "\$@" && return 0
                                                    echo "apt command failed, retry \${attempt}/3: \$*" >&2
                                                    sleep \$((attempt * 10))
                                                done
                                                "\$@"
                                            }
                                            apt_retry apt-get -o DPkg::Lock::Timeout=600 update
                                            apt_retry apt-get -o DPkg::Lock::Timeout=600 install -y build-essential "linux-headers-\$(uname -r)" kmod
                                        elif command -v dnf >/dev/null 2>&1; then
                                            dnf install -y make gcc kernel-devel kmod
                                        elif command -v yum >/dev/null 2>&1; then
                                            yum install -y make gcc kernel-devel kmod
                                        fi
                                    fi
                                    cd ${remoteDir}/kernel_driver/drivers/draid
                                    make
                                    test -f ./draid.ko
                                    module_name=\$(modinfo -F name ./draid.ko 2>/dev/null || true)
                                    module_name=\${module_name:-draid}
                                    echo "draid.ko module name: \${module_name}"
                                    for candidate in "\${module_name}" draid; do
                                        if [ -n "\${candidate}" ] && grep -q "^\${candidate} " /proc/modules; then
                                            rmmod "\${candidate}" || modprobe -r "\${candidate}"
                                        fi
                                    done
                                    for candidate in "\${module_name}" draid; do
                                        if [ -n "\${candidate}" ] && grep -q "^\${candidate} " /proc/modules; then
                                            echo "kernel module \${candidate} is still loaded after remove attempt" >&2
                                            grep -i draid /proc/modules >&2 || true
                                            exit 1
                                        fi
                                    done
                                    if ! insmod ./draid.ko; then
                                        echo "insmod ./draid.ko failed. Current related modules:" >&2
                                        grep -i draid /proc/modules >&2 || true
                                        exit 1
                                    fi
                                    grep -q "^\${module_name} " /proc/modules
                                '
fi
} 2>&1 | tee -a ${envPrepareLog}
"""
                                )
                                if (driverStatus != 0) {
                                    sh "printf '%s\\n' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${envPrepareLog}"
                                    error "[${ip}] build and reload draid kernel driver failed with exit code ${driverStatus}"
                                }

                                echo "[${ip}] install python dependencies"
                                def pythonDepsStatus = sh(
                                    returnStatus: true,
                                    script: """#!/bin/bash
set -o pipefail
{
echo "[${ip}] install python dependencies"
                                ${targetSsh} '
                                    cd ${remoteDir}
                                    need_test_deps=0
                                    python3 -c "import pytest" >/dev/null 2>&1 || need_test_deps=1
                                    if [ "${qemuEnv}" = "1" ]; then
                                        for tool in fio nvme lspci findmnt lsblk; do
                                            command -v "\${tool}" >/dev/null 2>&1 || need_test_deps=1
                                        done
                                    fi
                                    if [ "\${need_test_deps}" = "1" ]; then
                                        if command -v apt-get >/dev/null 2>&1; then
                                            export DEBIAN_FRONTEND=noninteractive
                                            apt_retry() {
                                                for attempt in 1 2 3; do
                                                    "\$@" && return 0
                                                    echo "apt command failed, retry \${attempt}/3: \$*" >&2
                                                    sleep \$((attempt * 10))
                                                done
                                                "\$@"
                                            }
                                            apt_retry apt-get -o DPkg::Lock::Timeout=600 update
                                            if [ "${qemuEnv}" = "1" ]; then
                                                apt_retry apt-get -o DPkg::Lock::Timeout=600 install -y \
                                                    python3-pip python3-pytest python-is-python3 \
                                                    fio nvme-cli pciutils util-linux smartmontools sdparm \
                                                    sysstat gawk nmap bc psmisc numactl lsscsi unzip \
                                                    xfsprogs parted make gcc g++
                                            else
                                                apt_retry apt-get -o DPkg::Lock::Timeout=600 install -y python3-pip python3-pytest
                                            fi
                                        elif command -v dnf >/dev/null 2>&1; then
                                            if [ "${qemuEnv}" = "1" ]; then
                                                dnf install -y python3-pip python3-pytest fio nvme-cli pciutils util-linux \
                                                    smartmontools sdparm sysstat gawk nmap bc psmisc numactl lsscsi unzip \
                                                    xfsprogs parted make gcc gcc-c++
                                            else
                                                dnf install -y python3-pip python3-pytest
                                            fi
                                        elif command -v yum >/dev/null 2>&1; then
                                            if [ "${qemuEnv}" = "1" ]; then
                                                yum install -y python3-pip python3-pytest fio nvme-cli pciutils util-linux \
                                                    smartmontools sdparm sysstat gawk nmap bc psmisc numactl lsscsi unzip \
                                                    xfsprogs parted make gcc gcc-c++
                                            else
                                                yum install -y python3-pip python3-pytest
                                            fi
                                        elif command -v zypper >/dev/null 2>&1; then
                                            if [ "${qemuEnv}" = "1" ]; then
                                                zypper install -y python3-pip python3-pytest fio nvme-cli pciutils util-linux \
                                                    smartmontools sdparm sysstat gawk nmap bc psmisc numactl lsscsi unzip \
                                                    xfsprogs parted make gcc gcc-c++
                                            else
                                                zypper install -y python3-pip python3-pytest
                                            fi
                                        fi
                                    fi

                                    if ! python3 -c "import pytest" >/dev/null 2>&1; then
                                        python3 -m pip --version >/dev/null 2>&1 || python3 -m ensurepip --default-pip >/dev/null 2>&1 || true
                                        if python3 -m pip install --help 2>/dev/null | grep -q -- "--break-system-packages"; then
                                            python3 -m pip install --break-system-packages pytest
                                        else
                                            python3 -m pip install pytest
                                        fi
                                    fi

                                    if python3 -m pip --version >/dev/null 2>&1; then
                                        if python3 -m pip install --help 2>/dev/null | grep -q -- "--break-system-packages"; then
                                            python3 -m pip install --break-system-packages allure-pytest || true
                                        else
                                            python3 -m pip install allure-pytest || true
                                        fi
                                    fi
                                    python3 -c "import pytest"
                                    if [ "${qemuEnv}" = "1" ]; then
                                        missing_tools=""
                                        for tool in fio nvme lspci findmnt lsblk; do
                                            if ! command -v "\$tool" >/dev/null 2>&1; then
                                                missing_tools="\${missing_tools} \${tool}"
                                            fi
                                        done
                                        if [ -n "\$missing_tools" ]; then
                                            echo "Missing required QEMU VM test tools after auto install:\${missing_tools}" >&2
                                            exit 1
                                        fi
                                    fi
                                '
} 2>&1 | tee -a ${envPrepareLog}
"""
                                )
                                if (pythonDepsStatus != 0) {
                                    sh "printf '%s\\n' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${envPrepareLog}"
                                    error "[${ip}] install python dependencies failed with exit code ${pythonDepsStatus}"
                                }
                                sh "printf '%s\\n' 'ENVIRONMENT_PREPARE_STATUS=passed' >> ${envPrepareLog}"

                                echo "[${ip}] collect environment metadata"
                                sh """
                                ${targetSsh} '
                                    cd ${remoteDir}
                                    mkdir -p allure-results
                                    {
                                        echo "Node_${ip}_Host=\$(hostname)"
                                        echo "Node_${ip}_Kernel=\$(uname -r)"
                                        echo "Node_${ip}_NVMe_Count=\$(ls /dev/nvme*n1 2>/dev/null | wc -l)"
                                    } > allure-results/environment_${ip}.properties
                                '
                                """

                                echo "[${ip}] run nvme_raid_test.py"
                                def testStatus = sh(
                                    returnStatus: true,
                                    script: """#!/bin/bash
set -o pipefail
timeout --kill-after=60s ${env.TARGET_NODE_TIMEOUT_MINUTES}m ${targetSsh} \"
    cd ${remoteDir} && \
    QEMU_VM_TARGET=${qemuEnv} \
    ALLOW_DESTRUCTIVE_FIO=${env.ALLOW_DESTRUCTIVE_FIO} \
    sudo -E python3 nvme_raid_test.py
\" 2>&1 | awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), \$0 }' | tee test_execution_${ip}.log
test_rc=\${PIPESTATUS[0]}
if [ "\$test_rc" = "124" ] || [ "\$test_rc" = "137" ]; then
    echo "[${ip}] ERROR: nvme_raid_test.py timed out after ${env.TARGET_NODE_TIMEOUT_MINUTES} minutes, target may be hung." | tee -a test_execution_${ip}.log
fi
exit "\$test_rc"
"""
                                )

                                echo "[${ip}] copy back reports"
                                sh """
                                mkdir -p allure-results
                                rm -rf allure-results-${ip}
                                ${targetScp} -r ${env.TARGET_USER}@${ip}:${remoteDir}/allure-results ./allure-results-${ip} || true
                                if [ -d allure-results-${ip} ]; then
                                    cp -R allure-results-${ip}/. ./allure-results/ || true
                                    rm -rf allure-results-${ip}
                                fi
                                ${targetScp} ${env.TARGET_USER}@${ip}:${remoteDir}/report.xml ./report_${ip}.xml || true
                                """

                                if (testStatus != 0) {
                                    error "[${ip}] nvme_raid_test.py failed with exit code ${testStatus}"
                                }

                                if (!fileExists("report_${ip}.xml")) {
                                    error "[${ip}] Missing report_${ip}.xml. nvme_raid_test.py did not produce a JUnit report."
                                }

                                if (qemuVmForNode && automaticMrTriggered) {
                                    def hostRemoteDir = "/root/Cyril/Jenkins/jenkins_nvme_${env.BUILD_NUMBER}_physical"
                                    def hostEnvPrepareLog = "environment_prepare_${ip}_physical.log"
                                    def hostSsh = "ssh ${env.SSH_OPTS} ${env.TARGET_USER}@${ip}"
                                    def hostScp = "scp ${env.SSH_OPTS}"

                                    writeFile file: hostEnvPrepareLog, text: "[${ip}] Physical Environment_Prepare started after QEMU VM test\n"

                                    echo "[${ip}] stop QEMU VM and return NVMe devices to physical host"
                                    def handbackStatus = sh(
                                        returnStatus: true,
                                        script: """#!/bin/bash
set -o pipefail
{
echo "[${ip}] stop QEMU VM and return NVMe devices to physical host"
${targetSsh} 'sync; nohup sh -c "sleep 1; poweroff" >/dev/null 2>&1 &' >/dev/null 2>&1 || true
for attempt in \$(seq 1 30); do
    if ${targetSsh} 'true' >/dev/null 2>&1; then
        echo "[${ip}] waiting for QEMU VM shutdown, attempt \${attempt}/30"
        sleep 2
    else
        echo "[${ip}] QEMU VM SSH is down"
        break
    fi
done
${hostSsh} '
    set -eu
    cd ${env.QEMU_VM_WORKDIR}
    test -x ${env.QEMU_VFIO_BIND_SCRIPT} || {
        echo "QEMU vfio bind script not found or not executable: ${env.QEMU_VM_WORKDIR}/${env.QEMU_VFIO_BIND_SCRIPT}" >&2
        exit 1
    }
    device_file=.jenkins_nvme_${env.BUILD_NUMBER}_vfio_devices
    if [ ! -s "\$device_file" ]; then
        echo "[${ip}] no recorded QEMU vfio devices to unbind"
        for pci_path in /sys/bus/pci/devices/*; do
            [ -e "\$pci_path/class" ] || continue
            [ "\$(cat "\$pci_path/class")" = "0x010802" ] || continue
            driver=\$(basename "\$(readlink -f "\$pci_path/driver" 2>/dev/null || true)")
            [ "\$driver" = "vfio-pci" ] || continue
            dev=\$(basename "\$pci_path")
            echo "[${ip}] fallback unbind vfio NVMe PCI device back to host: \$dev"
            DEV="\$dev" ${env.QEMU_VFIO_BIND_SCRIPT} unbind
        done
    else
        while read -r dev; do
            [ -n "\$dev" ] || continue
            echo "[${ip}] unbind NVMe PCI device back to host: \$dev"
            DEV="\$dev" ${env.QEMU_VFIO_BIND_SCRIPT} unbind
        done < "\$device_file"
    fi
    echo 1 > /sys/bus/pci/rescan
    sleep 5
    nvme list || true
'
} 2>&1 | tee -a ${hostEnvPrepareLog}
"""
                                    )
                                    if (handbackStatus != 0) {
                                        sh "printf '%s\\n' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${hostEnvPrepareLog}"
                                        error "[${ip}] returning NVMe devices to physical host failed with exit code ${handbackStatus}"
                                    }

                                    echo "[${ip}] deploy workspace for physical host test"
                                    def hostDeployStatus = sh(
                                        returnStatus: true,
                                        script: """#!/bin/bash
set -o pipefail
{
echo "[${ip}] deploy workspace for physical host test"
${hostSsh} 'rm -rf ${hostRemoteDir} && mkdir -p ${hostRemoteDir}'
tar \\
  --exclude='./.git' \\
  --exclude='./kernel_driver/.git' \\
  --exclude='./raid_cli' \\
  --exclude='./.pytest_cache' \\
  --exclude='./__pycache__' \\
  --exclude='./allure-results' \\
  --exclude='./report.xml' \\
  --exclude='./report_*.xml' \\
  --exclude='./test_execution_*.log' \\
  --exclude='./environment_prepare_*.log' \\
  --exclude='./feishu_payload.json' \\
  -czf - . | ${hostSsh} 'tar -xzf - -C ${hostRemoteDir}'
} 2>&1 | tee -a ${hostEnvPrepareLog}
"""
                                    )
                                    if (hostDeployStatus != 0) {
                                        sh "printf '%s\\n' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${hostEnvPrepareLog}"
                                        error "[${ip}] deploy physical host workspace failed with exit code ${hostDeployStatus}"
                                    }

                                    echo "[${ip}] install latest dpraid on physical host"
                                    def hostDpraidStatus = sh(
                                        returnStatus: true,
                                        script: """#!/bin/bash
set -o pipefail
{
echo "[${ip}] install latest dpraid on physical host"
${hostScp} '${raidCliDpraidPathForRun}' ${env.TARGET_USER}@${ip}:/tmp/dpraid_${env.BUILD_NUMBER}_physical
${hostSsh} '
    install -m 0755 /tmp/dpraid_${env.BUILD_NUMBER}_physical /usr/bin/dpraid
    rm -f /tmp/dpraid_${env.BUILD_NUMBER}_physical
    /usr/bin/dpraid --help >/dev/null 2>&1 || true
'
} 2>&1 | tee -a ${hostEnvPrepareLog}
"""
                                    )
                                    if (hostDpraidStatus != 0) {
                                        sh "printf '%s\\n' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${hostEnvPrepareLog}"
                                        error "[${ip}] install physical host dpraid failed with exit code ${hostDpraidStatus}"
                                    }

                                    echo "[${ip}] build and reload draid kernel driver on physical host"
                                    def hostDriverStatus = sh(
                                        returnStatus: true,
                                        script: """#!/bin/bash
set -o pipefail
{
echo "[${ip}] build and reload draid kernel driver on physical host"
${hostSsh} '
    set -eu
    need_driver_deps=0
    for tool in make gcc insmod modinfo; do
        command -v "\$tool" >/dev/null 2>&1 || need_driver_deps=1
    done
    [ -e "/lib/modules/\$(uname -r)/build" ] || need_driver_deps=1
    if [ "\$need_driver_deps" = "1" ]; then
        if command -v apt-get >/dev/null 2>&1; then
            export DEBIAN_FRONTEND=noninteractive
            apt_retry() {
                for attempt in 1 2 3; do
                    "\$@" && return 0
                    echo "apt command failed, retry \${attempt}/3: \$*" >&2
                    sleep \$((attempt * 10))
                done
                "\$@"
            }
            apt_retry apt-get -o DPkg::Lock::Timeout=600 update
            apt_retry apt-get -o DPkg::Lock::Timeout=600 install -y build-essential "linux-headers-\$(uname -r)" kmod
        elif command -v dnf >/dev/null 2>&1; then
            dnf install -y make gcc kernel-devel kmod
        elif command -v yum >/dev/null 2>&1; then
            yum install -y make gcc kernel-devel kmod
        fi
    fi
    cd ${hostRemoteDir}/kernel_driver/drivers/draid
    make
    test -f ./draid.ko
    module_name=\$(modinfo -F name ./draid.ko 2>/dev/null || true)
    module_name=\${module_name:-draid}
    echo "draid.ko module name: \${module_name}"
    for candidate in "\${module_name}" draid; do
        if [ -n "\${candidate}" ] && grep -q "^\${candidate} " /proc/modules; then
            rmmod "\${candidate}" || modprobe -r "\${candidate}"
        fi
    done
    for candidate in "\${module_name}" draid; do
        if [ -n "\${candidate}" ] && grep -q "^\${candidate} " /proc/modules; then
            echo "kernel module \${candidate} is still loaded after remove attempt" >&2
            grep -i draid /proc/modules >&2 || true
            exit 1
        fi
    done
    if ! insmod ./draid.ko; then
        echo "insmod ./draid.ko failed. Current related modules:" >&2
        grep -i draid /proc/modules >&2 || true
        exit 1
    fi
    grep -q "^\${module_name} " /proc/modules
'
} 2>&1 | tee -a ${hostEnvPrepareLog}
"""
                                    )
                                    if (hostDriverStatus != 0) {
                                        sh "printf '%s\\n' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${hostEnvPrepareLog}"
                                        error "[${ip}] build and reload physical host draid kernel driver failed with exit code ${hostDriverStatus}"
                                    }

                                    echo "[${ip}] install python dependencies on physical host"
                                    def hostPythonDepsStatus = sh(
                                        returnStatus: true,
                                        script: """#!/bin/bash
set -o pipefail
{
echo "[${ip}] install python dependencies on physical host"
${hostSsh} '
    cd ${hostRemoteDir}
    if ! python3 -c "import pytest" >/dev/null 2>&1; then
        if command -v apt-get >/dev/null 2>&1; then
            export DEBIAN_FRONTEND=noninteractive
            apt-get -o DPkg::Lock::Timeout=600 update
            apt-get -o DPkg::Lock::Timeout=600 install -y python3-pip python3-pytest
        elif command -v dnf >/dev/null 2>&1; then
            dnf install -y python3-pip python3-pytest
        elif command -v yum >/dev/null 2>&1; then
            yum install -y python3-pip python3-pytest
        elif command -v zypper >/dev/null 2>&1; then
            zypper install -y python3-pip python3-pytest
        fi
    fi
    python3 -c "import pytest"
'
} 2>&1 | tee -a ${hostEnvPrepareLog}
"""
                                    )
                                    if (hostPythonDepsStatus != 0) {
                                        sh "printf '%s\\n' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${hostEnvPrepareLog}"
                                        error "[${ip}] install physical host python dependencies failed with exit code ${hostPythonDepsStatus}"
                                    }
                                    sh "printf '%s\\n' 'ENVIRONMENT_PREPARE_STATUS=passed' >> ${hostEnvPrepareLog}"

                                    echo "[${ip}] collect physical host environment metadata"
                                    sh """
                                    ${hostSsh} '
                                        cd ${hostRemoteDir}
                                        mkdir -p allure-results
                                        {
                                            echo "Node_${ip}_Physical_Host=\$(hostname)"
                                            echo "Node_${ip}_Physical_Kernel=\$(uname -r)"
                                            echo "Node_${ip}_Physical_NVMe_Count=\$(ls /dev/nvme*n1 2>/dev/null | wc -l)"
                                        } > allure-results/environment_${ip}_physical.properties
                                    '
                                    """

                                    echo "[${ip}] run nvme_raid_test.py on physical host"
                                    def hostTestStatus = sh(
                                        returnStatus: true,
                                        script: """#!/bin/bash
set -o pipefail
timeout --kill-after=60s ${env.TARGET_NODE_TIMEOUT_MINUTES}m ${hostSsh} \"
    cd ${hostRemoteDir} && \
    QEMU_VM_TARGET=0 \
    ALLOW_DESTRUCTIVE_FIO=${env.ALLOW_DESTRUCTIVE_FIO} \
    sudo -E python3 nvme_raid_test.py
\" 2>&1 | awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), \$0 }' | tee test_execution_${ip}_physical.log
test_rc=\${PIPESTATUS[0]}
if [ "\$test_rc" = "124" ] || [ "\$test_rc" = "137" ]; then
    echo "[${ip}] ERROR: physical host nvme_raid_test.py timed out after ${env.TARGET_NODE_TIMEOUT_MINUTES} minutes, target may be hung." | tee -a test_execution_${ip}_physical.log
fi
exit "\$test_rc"
"""
                                    )

                                    echo "[${ip}] copy back physical host reports"
                                    sh """
                                    mkdir -p allure-results
                                    rm -rf allure-results-${ip}-physical
                                    ${hostScp} -r ${env.TARGET_USER}@${ip}:${hostRemoteDir}/allure-results ./allure-results-${ip}-physical || true
                                    if [ -d allure-results-${ip}-physical ]; then
                                        cp -R allure-results-${ip}-physical/. ./allure-results/ || true
                                        rm -rf allure-results-${ip}-physical
                                    fi
                                    ${hostScp} ${env.TARGET_USER}@${ip}:${hostRemoteDir}/report.xml ./report_${ip}_physical.xml || true
                                    """

                                    if (hostTestStatus != 0) {
                                        error "[${ip}] physical host nvme_raid_test.py failed with exit code ${hostTestStatus}"
                                    }

                                    if (!fileExists("report_${ip}_physical.xml")) {
                                        error "[${ip}] Missing report_${ip}_physical.xml. physical host nvme_raid_test.py did not produce a JUnit report."
                                    }
                                }
                            }
                        }
                    }

                    parallel parallelTasks
                }
            }
        }

    }

    post {
        always {
            script {
                if (params.RESTORE) {
                    echo 'Restore-only build finished.'
                    return
                }

                if (!shouldRunTests) {
                    echo 'No kernel_driver merge request event detected. Nothing to report.'
                    return
                }

                sh 'sudo chown -R jenkins:jenkins . || true'

                sh '''
                mkdir -p allure-results
                cat allure-results/environment_*.properties > allure-results/environment.properties 2>/dev/null || true
                rm -f allure-results/environment_*.properties
                python3 ci/junit_to_allure.py
                '''

                junit testResults: 'report_*.xml', allowEmptyResults: true

                allure(
                    includeProperties: true,
                    jdk: '',
                    reportName: 'TEST REPORT',
                    results: [[path: 'allure-results']]
                )

                archiveArtifacts artifacts: 'test_execution_*.log, environment_prepare_*.log, allure-results/monitor_log_*.tar.gz', allowEmptyArchive: true

                def metricsOutput = sh(script: "python3 ci/report_metrics.py", returnStdout: true).trim()

                def metrics = metricsOutput.split(' ')
                def total = metrics[0].toInteger()
                def failed = metrics[1].toInteger()
                def errors = metrics[2].toInteger()
                def skipped = metrics[3].toInteger()

                def passed = total - failed - errors - skipped
                def execRate = total > 0 ? String.format('%.2f%%', ((total - skipped) / (double) total) * 100) : '0%'
                def passRate = total > 0 ? String.format('%.1f%%', (passed / (double) total) * 100) : '0%'

                def startStr = new Date(currentBuild.startTimeInMillis).format('yyyy-MM-dd HH:mm:ss')
                def endStr = new Date().format('yyyy-MM-dd HH:mm:ss')
                def statusColor = (failed + errors == 0 && total > 0) ? 'blue' : 'red'
                def fontColor = statusColor == 'blue' ? 'green' : 'red'
                def ipListStr = targetIPs.join(', ')
                if (!raidCliCommit || raidCliCommit == 'unknown') {
                    def jenkinsHome = env.JENKINS_HOME ?: '/var/lib/jenkins'
                    def raidCliMarkerName = "${env.JOB_NAME}_${env.RAID_CLI_BRANCH}_raid_cli_commit".replaceAll('[^A-Za-z0-9_.-]', '_')
                    def raidCliRepoPath = "${jenkinsHome}/.raid_nvme/${raidCliMarkerName}.repo"
                    raidCliFullCommit = sh(
                        script: "git -C '${raidCliRepoPath}' rev-parse HEAD 2>/dev/null || echo unknown",
                        returnStdout: true
                    ).trim()
                    raidCliCommit = sh(
                        script: "git -C '${raidCliRepoPath}' rev-parse --short HEAD 2>/dev/null || echo unknown",
                        returnStdout: true
                    ).trim()
                }
                def driverLines = []
                if (kernelDriverMrIid) {
                    driverLines << "MR: !${kernelDriverMrIid} ${kernelDriverMrTitle ?: ''}".trim()
                    driverLines << "Source: ${kernelDriverRef ?: 'unknown'}"
                    driverLines << "Updated: ${kernelDriverMrUpdatedAt ?: 'unknown'}"
                } else {
                    driverLines << "Branch: ${kernelDriverRef ?: env.KERNEL_DRIVER_BRANCH}"
                }
                driverLines << "Commit: ${kernelDriverCommit ?: 'unknown'}"
                driverLines << "raid_cli(${env.RAID_CLI_BRANCH}): ${raidCliCommit ?: 'unknown'}"

                def actions = [[
                    tag: 'button',
                    text: [tag: 'plain_text', content: '查看报告'],
                    url: "${env.BUILD_URL}allure/",
                    type: 'primary'
                ]]
                if (kernelDriverMrUrl) {
                    actions << [
                        tag: 'button',
                        text: [tag: 'plain_text', content: '查看 MR'],
                        url: kernelDriverMrUrl,
                        type: 'default'
                    ]
                }

                def payload = [
                    msg_type: 'interactive',
                    card: [
                        config: [wide_screen_mode: true],
                        header: [
                            title: [tag: 'plain_text', content: 'NVMe_RAID(F6501) Test Report'],
                            template: statusColor
                        ],
                        elements: [
                            [
                                tag: 'div',
                                fields: [
                                    [is_short: true, text: [tag: 'lark_md', content: "**用户名:** dapustor"]],
                                    [is_short: true, text: [tag: 'lark_md', content: "**密码:** Admin@9000"]],
                                    [is_short: false, text: [tag: 'lark_md', content: "**触发来源:**\n${triggerSource ?: 'unknown'}"]],
                                    [is_short: false, text: [tag: 'lark_md', content: "**被测驱动:**\n${driverLines.join('\n')}"]],
                                    [is_short: false, text: [tag: 'lark_md', content: "**时间周期:**\n${startStr} ~ ${endStr}"]],
                                    [is_short: false, text: [tag: 'lark_md', content: "**并发节点:**\n${ipListStr}"]]
                                ]
                            ],
                            [
                                tag: 'div',
                                text: [
                                    tag: 'lark_md',
                                    content: "通过 **${passed}**  失败 **${failed}**  错误 **${errors}**  Total: **${total}**\n执行率: ${execRate}   通过率: <font color=\"${fontColor}\">${passRate}</font>"
                                ]
                            ],
                            [
                                tag: 'action',
                                actions: actions
                            ]
                        ]
                    ]
                ]

                writeFile file: 'feishu_payload.json', text: groovy.json.JsonOutput.toJson(payload)
                if (params.DEBUG_NO_FEISHU) {
                    echo 'DEBUG_NO_FEISHU=true, skip Feishu notification.'
                } else {
                    sh "curl -s -X POST -H 'Content-Type: application/json' -d @feishu_payload.json ${env.FEISHU_WEBHOOK}"
                }
            }
        }
    }
}
