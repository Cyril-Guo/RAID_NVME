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
    chmod +x ci/deploy_workspace.sh
    NODE_IP='${ip}' TARGET_USER='${targetUser}' SSH_OPTS='${sshOpts}' REMOTE_DIR='${remoteDir}' ci/deploy_workspace.sh
    """
}

def runTimedEnvironmentStep(ip, label, envPrepareLog, timeoutMinutes, scriptText) {
    def stepStatus = 0
    try {
        timeout(time: timeoutMinutes.toInteger(), unit: 'MINUTES') {
            stepStatus = sh(returnStatus: true, script: scriptText)
        }
    } catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException e) {
        sh "printf '%s\\n%s\\n' '[${ip}] ERROR: ${label} timed out after ${timeoutMinutes} minutes' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${envPrepareLog}"
        error "[${ip}] ${label} timed out after ${timeoutMinutes} minutes"
    }
    if (stepStatus != 0) {
        sh "printf '%s\\n%s\\n' '[${ip}] ERROR: ${label} failed with exit code ${stepStatus}' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${envPrepareLog}"
        error "[${ip}] ${label} failed with exit code ${stepStatus}"
    }
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
        TEST_IDLE_TIMEOUT_MINUTES = '15'
        ENVIRONMENT_STEP_TIMEOUT_MINUTES = '15'
        TEST_EXECUTION_ATTEMPTED = 'false'
        SSH_OPTS = '-o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ConnectTimeout=15'
        QEMU_VM_SSH_PORT = '2233'
        QEMU_VM_SCP_PORT = '2233'
        QEMU_VM_PASSWORD = '1'
        QEMU_VM_WORKDIR = '/root/Cyril/qemu'
        QEMU_VM_START_SCRIPT = './start_vm.sh'
        QEMU_KERNEL_BUILD_DIR = '/root/Cyril/qemu/general_kernel'
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

                                    python3 ci/gitlab_mr_to_properties.py kernel_driver_manual_mr.json > kernel_driver_manual_mr.properties
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

                                python3 ci/gitlab_mr_to_properties.py --list kernel_driver_mrs.json > kernel_driver_mr.properties
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
                            def markerEpochText = sh(
                                script: "stat -c %Y '${markerPath}' 2>/dev/null || echo 0",
                                returnStdout: true
                            ).trim()
                            def markerEpoch = (markerEpochText ==~ /^[0-9]+$/) ? markerEpochText.toLong() : 0L

                            def currentSignatures = currentMrSignature == 'none' ? [] : currentMrSignature.split('\\|') as List
                            def previousSignatures = previousMrSignature ? previousMrSignature.split('\\|') as List : []
                            if (!previousMrSignature && currentMrSignature != 'none') {
                                sh """
                                mkdir -p '${jenkinsHome}/.raid_nvme'
                                printf '%s\\n' '${currentMrSignature}' > '${markerPath}'
                                """
                                currentBuild.result = 'NOT_BUILT'
                                echo "kernel_driver MR marker bootstrap initialized. Existing open merge requests are recorded as baseline, skip tests."
                                return
                            }
                            previousSignatures = previousSignatures.collect { signature ->
                                def parts = signature.split(':')
                                parts.size() >= 3 ? "${parts[0]}:${parts[-1]}" : signature
                            }
                            def signatureByIid = { signatures ->
                                signatures.collectEntries { signature ->
                                    def parts = signature.split(':', 2)
                                    parts.size() == 2 && parts[0] ? [(parts[0]): signature] : [:]
                                }
                            }
                            def createdEpochByIid = (mrProps.MR_CREATED_EPOCH_SIGNATURE ?: '').split('\\|').collectEntries { item ->
                                def parts = item.split(':', 2)
                                parts.size() == 2 && parts[0] && parts[1] ==~ /^[0-9]+$/ ? [(parts[0]): parts[1].toLong()] : [:]
                            }
                            def currentByIid = signatureByIid(currentSignatures)
                            def previousByIid = signatureByIid(previousSignatures)
                            def existingMrShaChanged = currentByIid.any { iid, signature ->
                                previousByIid.containsKey(iid) && previousByIid[iid] != signature
                            }
                            def newlyCreatedMr = currentByIid.any { iid, signature ->
                                !previousByIid.containsKey(iid) && (createdEpochByIid[iid] ?: 0L) > markerEpoch
                            }
                            hasNewOpenMrEvent = existingMrShaChanged || newlyCreatedMr

                            if (!hasNewOpenMrEvent) {
                                if (currentMrSignature != 'none') {
                                    sh """
                                    mkdir -p '${jenkinsHome}/.raid_nvme'
                                    printf '%s\\n' '${currentMrSignature}' > '${markerPath}'
                                    """
                                }
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
                    env.TEST_EXECUTION_ATTEMPTED = 'true'
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
                    sh "test -d kernel_driver/drivers/draid && test -f kernel_driver/drivers/draid/Makefile"

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
                                    echo "[${ip}] reset QEMU VM and host devices before automatic MR test"
                                    def qemuPreCleanStatus = 0
                                    try {
                                        timeout(time: env.ENVIRONMENT_STEP_TIMEOUT_MINUTES.toInteger(), unit: 'MINUTES') {
                                            qemuPreCleanStatus = sh(
                                                returnStatus: true,
                                                script: """#!/bin/bash
set -o pipefail
chmod +x ci/qemu_vfio_cleanup.sh
NODE_IP='${ip}' \\
TARGET_USER='${env.TARGET_USER}' \\
SSH_OPTS='${env.SSH_OPTS}' \\
QEMU_VM_PASSWORD='${env.QEMU_VM_PASSWORD}' \\
QEMU_VM_SSH_PORT='${env.QEMU_VM_SSH_PORT}' \\
QEMU_VM_WORKDIR='${env.QEMU_VM_WORKDIR}' \\
QEMU_VFIO_BIND_SCRIPT='${env.QEMU_VFIO_BIND_SCRIPT}' \\
BUILD_NUMBER='${env.BUILD_NUMBER}' \\
CLEANUP_REASON='pre-test cleanup: stop existing QEMU VM and return vfio devices to physical host' \\
POWER_OFF_QEMU=1 \\
ci/qemu_vfio_cleanup.sh 2>&1 | tee -a ${envPrepareLog}
"""
                                            )
                                        }
                                    } catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException e) {
                                        sh "printf '%s\\n%s\\n' '[${ip}] ERROR: QEMU pre-test cleanup timed out after ${env.ENVIRONMENT_STEP_TIMEOUT_MINUTES} minutes' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${envPrepareLog}"
                                        error "[${ip}] QEMU pre-test cleanup timed out after ${env.ENVIRONMENT_STEP_TIMEOUT_MINUTES} minutes"
                                    }
                                    if (qemuPreCleanStatus != 0) {
                                        sh "printf '%s\\n%s\\n' '[${ip}] ERROR: QEMU pre-test cleanup failed with exit code ${qemuPreCleanStatus}' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${envPrepareLog}"
                                        error "[${ip}] QEMU pre-test cleanup failed with exit code ${qemuPreCleanStatus}"
                                    }

                                    echo "[${ip}] start QEMU VM for automatic MR test"
                                    def qemuStatus = 0
                                    try {
                                        timeout(time: env.ENVIRONMENT_STEP_TIMEOUT_MINUTES.toInteger(), unit: 'MINUTES') {
                                            qemuStatus = sh(
                                                returnStatus: true,
                                                script: """#!/bin/bash
set -o pipefail
chmod +x ci/qemu_vm_prepare.sh
NODE_IP='${ip}' \\
TARGET_USER='${env.TARGET_USER}' \\
SSH_OPTS='${env.SSH_OPTS}' \\
QEMU_VM_PASSWORD='${env.QEMU_VM_PASSWORD}' \\
QEMU_VM_SSH_PORT='${env.QEMU_VM_SSH_PORT}' \\
QEMU_VM_WORKDIR='${env.QEMU_VM_WORKDIR}' \\
QEMU_VM_START_SCRIPT='${env.QEMU_VM_START_SCRIPT}' \\
QEMU_VFIO_BIND_SCRIPT='${env.QEMU_VFIO_BIND_SCRIPT}' \\
RAID_CLI_DPRAID_PATH_FOR_RUN='${raidCliDpraidPathForRun}' \\
BUILD_NUMBER='${env.BUILD_NUMBER}' \\
ci/qemu_vm_prepare.sh 2>&1 | tee -a ${envPrepareLog}
"""
                                            )
                                        }
                                    } catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException e) {
                                        sh "printf '%s\\n%s\\n' '[${ip}] ERROR: QEMU VM startup timed out after ${env.ENVIRONMENT_STEP_TIMEOUT_MINUTES} minutes' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${envPrepareLog}"
                                        error "[${ip}] QEMU VM startup timed out after ${env.ENVIRONMENT_STEP_TIMEOUT_MINUTES} minutes"
                                    }
                                    if (qemuStatus != 0) {
                                        sh "printf '%s\\n%s\\n' '[${ip}] ERROR: QEMU VM startup failed with exit code ${qemuStatus}' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${envPrepareLog}"
                                        sh(
                                            returnStatus: true,
                                            script: """#!/bin/bash
set -o pipefail
chmod +x ci/qemu_vfio_cleanup.sh
NODE_IP='${ip}' \\
TARGET_USER='${env.TARGET_USER}' \\
SSH_OPTS='${env.SSH_OPTS}' \\
QEMU_VM_WORKDIR='${env.QEMU_VM_WORKDIR}' \\
QEMU_VFIO_BIND_SCRIPT='${env.QEMU_VFIO_BIND_SCRIPT}' \\
BUILD_NUMBER='${env.BUILD_NUMBER}' \\
CLEANUP_REASON='QEMU startup failed, return vfio devices to physical host' \\
ci/qemu_vfio_cleanup.sh 2>&1 | tee -a ${envPrepareLog}
"""
                                        )
                                        error "[${ip}] QEMU VM startup failed with exit code ${qemuStatus}"
                                    }
                                }

                                echo "[${ip}] deploy workspace"
                                runTimedEnvironmentStep(ip, 'deploy workspace', envPrepareLog, env.ENVIRONMENT_STEP_TIMEOUT_MINUTES, """#!/bin/bash
set -o pipefail
{
echo "[${ip}] deploy workspace"
if [ '${qemuEnv}' = '1' ]; then
    ${targetSsh} 'mkdir -p /root/Cyril/Jenkins && find /root/Cyril/Jenkins -maxdepth 1 -type d -name '"'"'jenkins_nvme_*'"'"' -exec rm -rf {} + && mkdir -p ${remoteDir}'
else
    ${targetSsh} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'
fi
chmod +x ci/deploy_workspace.sh
NODE_IP='${ip}' \\
TARGET_USER='${env.TARGET_USER}' \\
REMOTE_DIR='${remoteDir}' \\
REMOTE_SSH_COMMAND="${targetSsh}" \\
ci/deploy_workspace.sh
} 2>&1 | tee -a ${envPrepareLog}
""")

                                echo "[${ip}] install latest dpraid"
                                runTimedEnvironmentStep(ip, 'install latest dpraid', envPrepareLog, env.ENVIRONMENT_STEP_TIMEOUT_MINUTES, """#!/bin/bash
set -o pipefail
{
echo "[${ip}] install latest dpraid"
chmod +x ci/install_dpraid_remote.sh
NODE_IP='${ip}' \\
TARGET_USER='${env.TARGET_USER}' \\
SSH_OPTS='${env.SSH_OPTS}' \\
DPRAID_SOURCE='${raidCliDpraidPathForRun}' \\
BUILD_NUMBER='${env.BUILD_NUMBER}' \\
REMOTE_SSH_COMMAND="${targetSsh}" \\
REMOTE_SCP_COMMAND="${targetScp}" \\
ci/install_dpraid_remote.sh
} 2>&1 | tee -a ${envPrepareLog}
""")

                                echo "[${ip}] build and reload draid kernel driver"
                                runTimedEnvironmentStep(ip, 'build and reload draid kernel driver', envPrepareLog, env.ENVIRONMENT_STEP_TIMEOUT_MINUTES, """#!/bin/bash
set -o pipefail
{
echo "[${ip}] build and reload draid kernel driver"
chmod +x ci/prepare_draid_driver.sh
NODE_IP='${ip}' \\
TARGET_USER='${env.TARGET_USER}' \\
SSH_OPTS='${env.SSH_OPTS}' \\
REMOTE_DIR='${remoteDir}' \\
BUILD_NUMBER='${env.BUILD_NUMBER}' \\
QEMU_VM_TARGET='${qemuEnv}' \\
QEMU_VM_PASSWORD='${env.QEMU_VM_PASSWORD}' \\
QEMU_VM_SSH_PORT='${env.QEMU_VM_SSH_PORT}' \\
QEMU_VM_SCP_PORT='${env.QEMU_VM_SCP_PORT}' \\
QEMU_KERNEL_BUILD_DIR='${env.QEMU_KERNEL_BUILD_DIR}' \\
ci/prepare_draid_driver.sh
} 2>&1 | tee -a ${envPrepareLog}
""")

                                echo "[${ip}] install python dependencies"
                                runTimedEnvironmentStep(ip, 'install python dependencies', envPrepareLog, env.ENVIRONMENT_STEP_TIMEOUT_MINUTES, """#!/bin/bash
set -o pipefail
{
echo "[${ip}] install python dependencies"
${targetSsh} 'cd ${remoteDir} && chmod +x ci/install_test_dependencies.sh && QEMU_VM_TARGET=${qemuEnv} ci/install_test_dependencies.sh'
} 2>&1 | tee -a ${envPrepareLog}
""")
                                sh "printf '%s\\n' 'ENVIRONMENT_PREPARE_STATUS=passed' >> ${envPrepareLog}"

                                echo "[${ip}] collect environment metadata"
                                runTimedEnvironmentStep(ip, 'collect environment metadata', envPrepareLog, env.ENVIRONMENT_STEP_TIMEOUT_MINUTES, """#!/bin/bash
                                set -e
                                ${targetSsh} 'cd ${remoteDir} && chmod +x ci/collect_environment_metadata.sh && NODE_IP=${ip} REMOTE_DIR=${remoteDir} PREFIX=Node_${ip} ci/collect_environment_metadata.sh'
                                """)

                                echo "[${ip}] run nvme_raid_test.py and copy back reports"
                                def testStatus = sh(
                                    returnStatus: true,
                                    script: """#!/bin/bash
 chmod +x ci/run_remote_test_and_collect.sh
 NODE_IP='${ip}' \
 TARGET_USER='${env.TARGET_USER}' \
 REMOTE_DIR='${remoteDir}' \
 REMOTE_SSH_COMMAND="${targetSsh}" \
 REMOTE_SCP_COMMAND="${targetScp}" \
 TEST_IDLE_TIMEOUT_MINUTES='${env.TEST_IDLE_TIMEOUT_MINUTES}' \
 QEMU_VM_TARGET='${qemuEnv}' \
 ALLOW_DESTRUCTIVE_FIO='${env.ALLOW_DESTRUCTIVE_FIO}' \
 ci/run_remote_test_and_collect.sh
 """
                                )
                                if (testStatus != 0) {
                                    error "[${ip}] nvme_raid_test.py or report collection failed with exit code ${testStatus}"
                                }

                                if (qemuVmForNode && automaticMrTriggered) {
                                    echo "[${ip}] run physical host test after QEMU VM test"
                                    def hostStatus = sh(
                                        returnStatus: true,
                                        script: """#!/bin/bash
 chmod +x ci/run_physical_host_test.sh
 NODE_IP='${ip}' \
 TARGET_USER='${env.TARGET_USER}' \
 SSH_OPTS='${env.SSH_OPTS}' \
 QEMU_VM_PASSWORD='${env.QEMU_VM_PASSWORD}' \
 QEMU_VM_SSH_PORT='${env.QEMU_VM_SSH_PORT}' \
 QEMU_VM_WORKDIR='${env.QEMU_VM_WORKDIR}' \
 QEMU_VFIO_BIND_SCRIPT='${env.QEMU_VFIO_BIND_SCRIPT}' \
 BUILD_NUMBER='${env.BUILD_NUMBER}' \
 DPRAID_SOURCE='${raidCliDpraidPathForRun}' \
 TEST_IDLE_TIMEOUT_MINUTES='${env.TEST_IDLE_TIMEOUT_MINUTES}' \
 ALLOW_DESTRUCTIVE_FIO='${env.ALLOW_DESTRUCTIVE_FIO}' \
 ci/run_physical_host_test.sh
 """
                                    )
                                    if (hostStatus != 0) {
                                        error "[${ip}] physical host test failed with exit code ${hostStatus}"
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
                python3 ci/collect_console_output.py
                python3 ci/junit_to_allure.py
                '''

                junit testResults: 'report_*.xml', allowEmptyResults: true

                allure(
                    includeProperties: true,
                    jdk: '',
                    reportName: 'TEST REPORT',
                    results: [[path: 'allure-results']]
                )

                archiveArtifacts artifacts: 'jenkins_console.log, test_execution_*.log, environment_prepare_*.log, allure-results/monitor_log_*.tar.gz', allowEmptyArchive: true

                def metricsOutput = sh(script: "python3 ci/report_metrics.py", returnStdout: true).trim()

                def metrics = metricsOutput.split(' ')
                def total = metrics[0].toInteger()
                def failed = metrics[1].toInteger()
                def errors = metrics[2].toInteger()
                def skipped = metrics[3].toInteger()

                def startStr = new Date(currentBuild.startTimeInMillis).format('yyyy-MM-dd HH:mm:ss')
                def endStr = new Date().format('yyyy-MM-dd HH:mm:ss')
                def ipListStr = targetIPs.join(', ')
                def buildResult = currentBuild.currentResult ?: currentBuild.result ?: 'UNKNOWN'
                def testAttempted = (env.TEST_EXECUTION_ATTEMPTED == 'true')
                if (total == 0) {
                    echo "Skip Feishu notification: no reportable test or environment prepare result was generated in this build. testAttempted=${testAttempted}, result=${buildResult}"
                    return
                }
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
                withEnv([
                    "TOTAL=${total}",
                    "FAILED=${failed}",
                    "ERRORS=${errors}",
                    "SKIPPED=${skipped}",
                    "BUILD_RESULT=${buildResult}",
                    "START_STR=${startStr}",
                    "END_STR=${endStr}",
                    "IP_LIST=${ipListStr}",
                    "TRIGGER_SOURCE=${triggerSource ?: 'unknown'}",
                    "KERNEL_DRIVER_BRANCH=${env.KERNEL_DRIVER_BRANCH}",
                    "KERNEL_DRIVER_REF=${kernelDriverRef ?: ''}",
                    "KERNEL_DRIVER_COMMIT=${kernelDriverCommit ?: 'unknown'}",
                    "KERNEL_DRIVER_MR_IID=${kernelDriverMrIid ?: ''}",
                    "KERNEL_DRIVER_MR_TITLE=${kernelDriverMrTitle ?: ''}",
                    "KERNEL_DRIVER_MR_UPDATED_AT=${kernelDriverMrUpdatedAt ?: ''}",
                    "KERNEL_DRIVER_MR_URL=${kernelDriverMrUrl ?: ''}",
                    "RAID_CLI_BRANCH=${env.RAID_CLI_BRANCH}",
                    "RAID_CLI_COMMIT=${raidCliCommit ?: 'unknown'}",
                    "BUILD_URL=${env.BUILD_URL}"
                ]) {
                    sh 'python3 ci/build_feishu_payload.py'
                }
                if (!fileExists('feishu_payload.json')) {
                    echo 'Skip Feishu notification: feishu_payload.json was not generated.'
                    return
                }
                if (params.DEBUG_NO_FEISHU) {
                    echo 'DEBUG_NO_FEISHU=true, skip Feishu notification.'
                } else {
                    sh "curl -s -X POST -H 'Content-Type: application/json' -d @feishu_payload.json ${env.FEISHU_WEBHOOK}"
                }
            }
        }
    }
}
