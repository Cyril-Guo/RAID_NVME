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

def hostSshCmd(ip) {
    // Use sshpass -e so callers can also safely store/expand the command string.
    return "SSHPASS='${env.TARGET_PASSWORD}' sshpass -e ssh ${env.SSH_OPTS} ${env.TARGET_USER}@${ip}"
}

def hostScpCmd() {
    return "SSHPASS='${env.TARGET_PASSWORD}' sshpass -e scp ${env.SSH_OPTS}"
}

def sanitizePathSegment(value) {
    def text = (value ?: 'unknown').toString().trim()
    text = text.replaceAll('^origin/', '')
    text = text.replaceAll('[^A-Za-z0-9._-]', '_')
    if (!text) {
        text = 'unknown'
    }
    return text
}

def resolveRaidNvmeBranch() {
    // Prefer Jenkins-provided branch envs, then scm config, then git, then job name.
    // Freestyle/Pipeline jobs often lack BRANCH_NAME and check out detached HEAD.
    def branch = (
        env.BRANCH_NAME ?: env.GIT_BRANCH ?: env.CHANGE_BRANCH ?: ''
    ).toString().trim().replaceAll('^origin/', '')

    if (!branch || branch == 'HEAD') {
        try {
            def scmBranch = scm?.branches ? scm.branches[0]?.name?.toString() : ''
            branch = (scmBranch ?: '')
                .replaceAll('^\\*/', '')
                .replaceAll('^origin/', '')
                .trim()
        } catch (Exception ignored) {
            branch = ''
        }
    }

    if (!branch || branch == 'HEAD') {
        branch = sh(
            script: '''
set +e
b=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
if [ -n "$b" ] && [ "$b" != "HEAD" ]; then printf '%s\\n' "$b"; exit 0; fi
b=$(git name-rev --name-only --exclude='tags/*' HEAD 2>/dev/null \\
    | sed -e 's#^remotes/origin/##' -e 's#^origin/##' -e 's#\\^0$##')
if [ -n "$b" ] && [ "$b" != "undefined" ] && [ "$b" != "HEAD" ] && [[ "$b" != *"~"* ]]; then
    printf '%s\\n' "$b"
    exit 0
fi
printf '\\n'
''',
            returnStdout: true
        ).trim()
    }

    if (!branch || branch == 'HEAD') {
        // Job CI/SMOKE is named after the RAID_NVME branch it tracks.
        branch = (env.JOB_BASE_NAME ?: env.JOB_NAME ?: 'unknown').toString().trim()
    }
    return branch
}

// DUT layout: /root/Cyril/Jenkins/<JOB>/<BRANCH>/<build|restore|physical>-<N>
// Keeps CI/SMOKE, branches, and builds from mixing in one flat directory.
def remoteWorkspaceRoot(kind = 'build') {
    def job = sanitizePathSegment(env.JOB_BASE_NAME ?: env.JOB_NAME ?: 'job')
    def branch = sanitizePathSegment(resolveRaidNvmeBranch())
    def prefix = (kind == 'restore') ? 'restore' : ((kind == 'physical') ? 'physical' : 'build')
    return "/root/Cyril/Jenkins/${job}/${branch}/${prefix}-${env.BUILD_NUMBER}"
}

def copyWorkspaceToRemote(ip, remoteDir, targetUser, sshOpts) {
    sh """
    chmod +x ci/deploy_workspace.sh
    NODE_IP='${ip}' TARGET_USER='${targetUser}' SSH_OPTS='${sshOpts}' TARGET_PASSWORD='${env.TARGET_PASSWORD}' REMOTE_DIR='${remoteDir}' ci/deploy_workspace.sh
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

// Split node test flow into smaller methods to avoid Jenkins CPS "Method too large".
def smokeTargetSsh(ip, qemuVmForNode) {
    if (qemuVmForNode) {
        return "SSHPASS='${env.QEMU_VM_PASSWORD}' sshpass -e ssh ${env.SSH_OPTS} -p ${env.QEMU_VM_SSH_PORT} ${env.TARGET_USER}@${ip}"
    }
    return hostSshCmd(ip)
}

def smokeTargetScp(qemuVmForNode) {
    if (qemuVmForNode) {
        return "SSHPASS='${env.QEMU_VM_PASSWORD}' sshpass -e scp ${env.SSH_OPTS} -P ${env.QEMU_VM_SCP_PORT}"
    }
    return hostScpCmd()
}

def prepareSmokeQemuScene(ip, envPrepareLog, raidCliDpraidPathForRun) {
    echo "[${ip}] reset QEMU VM and host devices before automatic MR test"
    def qemuPreCleanStatus = 0
    try {
        timeout(time: env.ENVIRONMENT_STEP_TIMEOUT_MINUTES.toInteger(), unit: 'MINUTES') {
            qemuPreCleanStatus = sh(
                returnStatus: true,
                script: """#!/bin/bash
set -o pipefail
chmod +x ci/qemu_vfio_cleanup.sh
NODE_IP='${ip}' \
TARGET_USER='${env.TARGET_USER}' \
SSH_OPTS='${env.SSH_OPTS}' \
TARGET_PASSWORD='${env.TARGET_PASSWORD}' \
QEMU_VM_PASSWORD='${env.QEMU_VM_PASSWORD}' \
QEMU_VM_SSH_PORT='${env.QEMU_VM_SSH_PORT}' \
QEMU_VM_WORKDIR='${env.QEMU_VM_WORKDIR}' \
QEMU_VFIO_BIND_SCRIPT='${env.QEMU_VFIO_BIND_SCRIPT}' \
BUILD_NUMBER='${env.BUILD_NUMBER}' \
CLEANUP_REASON='pre-test cleanup: stop existing QEMU VM and return vfio devices to physical host' \
POWER_OFF_QEMU=1 \
ci/qemu_vfio_cleanup.sh 2>&1 | tee -a ${envPrepareLog}
"""
            )
        }
    } catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException e) {
        sh "printf '%s\n%s\n' '[${ip}] ERROR: QEMU pre-test cleanup timed out after ${env.ENVIRONMENT_STEP_TIMEOUT_MINUTES} minutes' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${envPrepareLog}"
        error "[${ip}] QEMU pre-test cleanup timed out after ${env.ENVIRONMENT_STEP_TIMEOUT_MINUTES} minutes"
    }
    if (qemuPreCleanStatus != 0) {
        sh "printf '%s\n%s\n' '[${ip}] ERROR: QEMU pre-test cleanup failed with exit code ${qemuPreCleanStatus}' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${envPrepareLog}"
        error "[${ip}] QEMU pre-test cleanup failed with exit code ${qemuPreCleanStatus}"
    }

    // Dirty CSD flash (8P/9P) is visible on the physical host after reclaim,
    // before devices are passed through to QEMU.
    // Use hostSshCmd/hostScpCmd directly (do not store sshpass -p '...' in a
    // bash variable and expand it — the quotes become part of the password).
    echo "[${ip}] clear dirty CSD flash on physical host before QEMU start"
    def flashClearSsh = hostSshCmd(ip)
    def flashClearScp = hostScpCmd()
    runTimedEnvironmentStep(ip, 'clear dirty CSD flash on physical host before QEMU start', envPrepareLog, env.ENVIRONMENT_STEP_TIMEOUT_MINUTES, """#!/bin/bash
set -o pipefail
{
echo "[${ip}] clear dirty CSD flash on physical host before QEMU start"
remote_clear_dir="/tmp/jenkins_nvme_${env.BUILD_NUMBER}_flash_clear"
${flashClearSsh} "rm -rf \${remote_clear_dir} && mkdir -p \${remote_clear_dir}"
chmod +x ci/clear_8p_csd_flash.sh ci/flash-clear.sh
${flashClearScp} ci/clear_8p_csd_flash.sh ci/flash-clear.sh ${env.TARGET_USER}@${ip}:\${remote_clear_dir}/
${flashClearSsh} "cd \${remote_clear_dir} && chmod +x clear_8p_csd_flash.sh flash-clear.sh && NODE_IP=${ip} ./clear_8p_csd_flash.sh"
} 2>&1 | tee -a ${envPrepareLog}
""")

    echo "[${ip}] start QEMU VM for automatic MR test"
    def qemuStatus = 0
    try {
        timeout(time: env.ENVIRONMENT_STEP_TIMEOUT_MINUTES.toInteger(), unit: 'MINUTES') {
            qemuStatus = sh(
                returnStatus: true,
                script: """#!/bin/bash
set -o pipefail
chmod +x ci/qemu_vm_prepare.sh
NODE_IP='${ip}' \
TARGET_USER='${env.TARGET_USER}' \
SSH_OPTS='${env.SSH_OPTS}' \
TARGET_PASSWORD='${env.TARGET_PASSWORD}' \
QEMU_VM_PASSWORD='${env.QEMU_VM_PASSWORD}' \
QEMU_VM_SSH_PORT='${env.QEMU_VM_SSH_PORT}' \
QEMU_VM_WORKDIR='${env.QEMU_VM_WORKDIR}' \
QEMU_VM_START_SCRIPT='${env.QEMU_VM_START_SCRIPT}' \
QEMU_VFIO_BIND_SCRIPT='${env.QEMU_VFIO_BIND_SCRIPT}' \
RAID_CLI_DPRAID_PATH_FOR_RUN='${raidCliDpraidPathForRun}' \
BUILD_NUMBER='${env.BUILD_NUMBER}' \
ci/qemu_vm_prepare.sh 2>&1 | tee -a ${envPrepareLog}
"""
            )
        }
    } catch (org.jenkinsci.plugins.workflow.steps.FlowInterruptedException e) {
        sh "printf '%s\n%s\n' '[${ip}] ERROR: QEMU VM startup timed out after ${env.ENVIRONMENT_STEP_TIMEOUT_MINUTES} minutes' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${envPrepareLog}"
        sh(
            returnStatus: true,
            script: """#!/bin/bash
set -o pipefail
chmod +x ci/qemu_vfio_cleanup.sh
NODE_IP='${ip}' \
TARGET_USER='${env.TARGET_USER}' \
SSH_OPTS='${env.SSH_OPTS}' \
QEMU_VM_PASSWORD='${env.QEMU_VM_PASSWORD}' \
QEMU_VM_SSH_PORT='${env.QEMU_VM_SSH_PORT}' \
QEMU_VM_WORKDIR='${env.QEMU_VM_WORKDIR}' \
QEMU_VFIO_BIND_SCRIPT='${env.QEMU_VFIO_BIND_SCRIPT}' \
BUILD_NUMBER='${env.BUILD_NUMBER}' \
TARGET_PASSWORD='${env.TARGET_PASSWORD}' \
CLEANUP_REASON='QEMU startup timed out before usable VM scene, return vfio devices to physical host' \
POWER_OFF_QEMU=1 \
ci/qemu_vfio_cleanup.sh 2>&1 | tee -a ${envPrepareLog}
"""
        )
        error "[${ip}] QEMU VM startup timed out after ${env.ENVIRONMENT_STEP_TIMEOUT_MINUTES} minutes"
    }
    if (qemuStatus != 0) {
        sh "printf '%s\n%s\n' '[${ip}] ERROR: QEMU VM startup failed with exit code ${qemuStatus}' 'ENVIRONMENT_PREPARE_STATUS=failed' >> ${envPrepareLog}"
        sh(
            returnStatus: true,
            script: """#!/bin/bash
set -o pipefail
chmod +x ci/qemu_vfio_cleanup.sh
NODE_IP='${ip}' \
TARGET_USER='${env.TARGET_USER}' \
SSH_OPTS='${env.SSH_OPTS}' \
QEMU_VM_PASSWORD='${env.QEMU_VM_PASSWORD}' \
QEMU_VM_SSH_PORT='${env.QEMU_VM_SSH_PORT}' \
QEMU_VM_WORKDIR='${env.QEMU_VM_WORKDIR}' \
QEMU_VFIO_BIND_SCRIPT='${env.QEMU_VFIO_BIND_SCRIPT}' \
BUILD_NUMBER='${env.BUILD_NUMBER}' \
TARGET_PASSWORD='${env.TARGET_PASSWORD}' \
CLEANUP_REASON='QEMU startup failed before usable VM scene, return vfio devices to physical host' \
POWER_OFF_QEMU=1 \
ci/qemu_vfio_cleanup.sh 2>&1 | tee -a ${envPrepareLog}
"""
        )
        error "[${ip}] QEMU VM startup failed with exit code ${qemuStatus}"
    }
}

def prepareSmokeNodeEnvironment(ip, remoteDir, envPrepareLog, targetSsh, targetScp, qemuEnv, qemuVmForNode, raidCliDpraidPathForRun) {
    echo "[${ip}] remote workspace: ${remoteDir}"
    echo "[${ip}] deploy workspace"
    runTimedEnvironmentStep(ip, 'deploy workspace', envPrepareLog, env.ENVIRONMENT_STEP_TIMEOUT_MINUTES, """#!/bin/bash
set -o pipefail
{
echo "[${ip}] deploy workspace -> ${remoteDir}"
${targetSsh} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'
chmod +x ci/deploy_workspace.sh
NODE_IP='${ip}' \
TARGET_USER='${env.TARGET_USER}' \
REMOTE_DIR='${remoteDir}' \
REMOTE_SSH_COMMAND="${targetSsh}" \
ci/deploy_workspace.sh
} 2>&1 | tee -a ${envPrepareLog}
""")

    if (!qemuVmForNode) {
        echo "[${ip}] clear dirty CSD flash before loading draid"
        runTimedEnvironmentStep(ip, 'clear dirty CSD flash before loading draid', envPrepareLog, env.ENVIRONMENT_STEP_TIMEOUT_MINUTES, """#!/bin/bash
set -o pipefail
{
echo "[${ip}] clear dirty CSD flash before loading draid"
${targetSsh} 'cd ${remoteDir} && chmod +x ci/clear_8p_csd_flash.sh ci/flash-clear.sh && NODE_IP=${ip} ci/clear_8p_csd_flash.sh'
} 2>&1 | tee -a ${envPrepareLog}
""")
    }

    echo "[${ip}] install latest dpraid"
    runTimedEnvironmentStep(ip, 'install latest dpraid', envPrepareLog, env.ENVIRONMENT_STEP_TIMEOUT_MINUTES, """#!/bin/bash
set -o pipefail
{
echo "[${ip}] install latest dpraid"
chmod +x ci/install_dpraid_remote.sh
NODE_IP='${ip}' \
TARGET_USER='${env.TARGET_USER}' \
SSH_OPTS='${env.SSH_OPTS}' \
DPRAID_SOURCE='${raidCliDpraidPathForRun}' \
BUILD_NUMBER='${env.BUILD_NUMBER}' \
REMOTE_SSH_COMMAND="${targetSsh}" \
REMOTE_SCP_COMMAND="${targetScp}" \
ci/install_dpraid_remote.sh
} 2>&1 | tee -a ${envPrepareLog}
""")

    echo "[${ip}] build and reload draid kernel driver"
    runTimedEnvironmentStep(ip, 'build and reload draid kernel driver', envPrepareLog, env.ENVIRONMENT_STEP_TIMEOUT_MINUTES, """#!/bin/bash
set -o pipefail
{
echo "[${ip}] build and reload draid kernel driver"
chmod +x ci/prepare_draid_driver.sh
NODE_IP='${ip}' \
TARGET_USER='${env.TARGET_USER}' \
SSH_OPTS='${env.SSH_OPTS}' \
TARGET_PASSWORD='${env.TARGET_PASSWORD}' \
REMOTE_DIR='${remoteDir}' \
BUILD_NUMBER='${env.BUILD_NUMBER}' \
QEMU_VM_TARGET='${qemuEnv}' \
QEMU_VM_PASSWORD='${env.QEMU_VM_PASSWORD}' \
QEMU_VM_SSH_PORT='${env.QEMU_VM_SSH_PORT}' \
QEMU_VM_SCP_PORT='${env.QEMU_VM_SCP_PORT}' \
QEMU_KERNEL_BUILD_DIR='${env.QEMU_KERNEL_BUILD_DIR}' \
ci/prepare_draid_driver.sh
} 2>&1 | tee -a ${envPrepareLog}
""")

    echo "[${ip}] restore RAID state before test"
    runTimedEnvironmentStep(ip, 'restore RAID state before test', envPrepareLog, env.ENVIRONMENT_STEP_TIMEOUT_MINUTES, """#!/bin/bash
set -o pipefail
{
echo "[${ip}] restore RAID state before test"
${targetSsh} 'cd ${remoteDir} && chmod +x ci/restore_physical_raid_state.sh && NODE_IP=${ip} ci/restore_physical_raid_state.sh'
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
    sh "printf '%s\n' 'ENVIRONMENT_PREPARE_STATUS=passed' >> ${envPrepareLog}"

    echo "[${ip}] collect environment metadata"
    runTimedEnvironmentStep(ip, 'collect environment metadata', envPrepareLog, env.ENVIRONMENT_STEP_TIMEOUT_MINUTES, """#!/bin/bash
set -e
${targetSsh} 'cd ${remoteDir} && chmod +x ci/collect_environment_metadata.sh && NODE_IP=${ip} REMOTE_DIR=${remoteDir} PREFIX=Node_${ip} ci/collect_environment_metadata.sh'
""")
}

def runSmokeNodeWorkloads(ip, remoteDir, targetSsh, targetScp, qemuEnv, qemuVmForNode, raidCliDpraidPathForRun) {
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
        if (qemuVmForNode) {
            echo "[${ip}] QEMU test failed; keep VM/vfio devices for failure analysis. Next triggered run will reclaim them in pre-test cleanup."
        }
        error "[${ip}] nvme_raid_test.py or report collection failed with exit code ${testStatus}"
    }

    if (qemuVmForNode && automaticMrTriggered) {
        echo "[${ip}] QEMU test passed; stop QEMU VM, return NVMe devices, then run physical host test"
        def hostStatus = sh(
            returnStatus: true,
            script: """#!/bin/bash
chmod +x ci/run_physical_host_test.sh
NODE_IP='${ip}' \
TARGET_USER='${env.TARGET_USER}' \
SSH_OPTS='${env.SSH_OPTS}' \
TARGET_PASSWORD='${env.TARGET_PASSWORD}' \
QEMU_VM_PASSWORD='${env.QEMU_VM_PASSWORD}' \
QEMU_VM_SSH_PORT='${env.QEMU_VM_SSH_PORT}' \
QEMU_VM_WORKDIR='${env.QEMU_VM_WORKDIR}' \
QEMU_VFIO_BIND_SCRIPT='${env.QEMU_VFIO_BIND_SCRIPT}' \
JOB_BASE_NAME='${env.JOB_BASE_NAME ?: env.JOB_NAME}' \
BRANCH_NAME='${env.BRANCH_NAME ?: env.GIT_BRANCH}' \
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

def markSmokeEnvironmentPrepareFailed(ip, envPrepareLog, reason) {
    // Ensure post/Allure/Feishu can always count a failed Environment_Prepare item.
    sh """
    mkdir -p .
    if [ ! -f '${envPrepareLog}' ]; then
      printf '%s\\n' '[${ip}] Environment_Prepare started' > '${envPrepareLog}'
    fi
    printf '%s\\n%s\\n' '[${ip}] ERROR: ${reason}' 'ENVIRONMENT_PREPARE_STATUS=failed' >> '${envPrepareLog}'
    """
}

def runSmokeNodeTest(ip, raidCliDpraidPathForRun) {
    // Keep stage() in the parallel closure (caller). Nested stage inside a
    // top-level method breaks CPS step allocation and can abort before any logs.
    def envPrepareLog = "environment_prepare_${ip}.log"
    def qemuVmForNode = useQemuVmTarget
    def targetSsh = smokeTargetSsh(ip, qemuVmForNode)
    def targetScp = smokeTargetScp(qemuVmForNode)
    def qemuEnv = qemuVmForNode ? '1' : '0'

    writeFile file: envPrepareLog, text: "[${ip}] Environment_Prepare started\n"

    try {
        def remoteDir = remoteWorkspaceRoot('build')
        if (qemuVmForNode) {
            prepareSmokeQemuScene(ip, envPrepareLog, raidCliDpraidPathForRun)
        }

        prepareSmokeNodeEnvironment(
            ip, remoteDir, envPrepareLog, targetSsh, targetScp, qemuEnv, qemuVmForNode, raidCliDpraidPathForRun
        )
        runSmokeNodeWorkloads(
            ip, remoteDir, targetSsh, targetScp, qemuEnv, qemuVmForNode, raidCliDpraidPathForRun
        )
    } catch (Exception e) {
        def reason = (e?.message ?: e?.toString() ?: 'unknown error').toString().take(300)
        def alreadyMarked = fileExists(envPrepareLog) &&
            readFile(envPrepareLog).contains('ENVIRONMENT_PREPARE_STATUS=')
        if (!alreadyMarked) {
            markSmokeEnvironmentPrepareFailed(ip, envPrepareLog, reason)
        }
        throw e
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
            description: 'Manual rerun: set a kernel_driver merge request IID, for example 141. Takes priority over MANUAL_KERNEL_DRIVER_REF.'
        )
        string(
            name: 'MANUAL_KERNEL_DRIVER_REF',
            defaultValue: '',
            trim: true,
            description: 'Manual build: kernel_driver branch to test. Empty means main; ignored when MANUAL_MR_IID is set.'
        )
        string(
            name: 'TARGET_PASSWORD',
            defaultValue: '123456',
            trim: true,
            description: 'Physical host SSH password for TARGET_USER (default 123456).'
        )
    }

    environment {
        FEISHU_WEBHOOK = credentials('feishu-webhook')
        TARGET_USER = 'root'
        TARGET_PASSWORD = "${params.TARGET_PASSWORD?.trim() ?: '123456'}"
        ALLOW_DESTRUCTIVE_FIO = '1'
        TEST_IDLE_TIMEOUT_MINUTES = '15'
        ENVIRONMENT_STEP_TIMEOUT_MINUTES = '15'
        TEST_EXECUTION_ATTEMPTED = 'false'
        SSH_OPTS = '-o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ConnectTimeout=15'
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

                sh 'chmod +x ci/ensure_sshpass.sh && ci/ensure_sshpass.sh'

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
                            def manualKernelDriverRef = (params.MANUAL_KERNEL_DRIVER_REF ?: '').trim()
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
                                if (manualKernelDriverRef) {
                                    echo "MANUAL_MR_IID is set; ignore MANUAL_KERNEL_DRIVER_REF=${manualKernelDriverRef}."
                                }
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
                                if (manualKernelDriverRef) {
                                    if (!(manualKernelDriverRef ==~ '[A-Za-z0-9][A-Za-z0-9._/-]*') ||
                                        manualKernelDriverRef.contains('..') ||
                                        manualKernelDriverRef.endsWith('/')) {
                                        error "MANUAL_KERNEL_DRIVER_REF is not a safe branch name: ${manualKernelDriverRef}"
                                    }
                                    kernelDriverRef = manualKernelDriverRef
                                    triggerSource = params.SIMULATE_AUTO_MR_TRIGGER ? 'Manual Branch Build (Simulate Auto MR)' : 'Manual Branch Build'
                                } else {
                                    kernelDriverRef = env.KERNEL_DRIVER_BRANCH
                                    triggerSource = params.SIMULATE_AUTO_MR_TRIGGER ? 'Manual Build (Simulate Auto MR)' : 'Manual Build'
                                }
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
                            def changedIids = []
                            currentByIid.each { iid, signature ->
                                if (previousByIid.containsKey(iid) && previousByIid[iid] != signature) {
                                    changedIids.add(iid)
                                } else if (!previousByIid.containsKey(iid) && (createdEpochByIid[iid] ?: 0L) > markerEpoch) {
                                    changedIids.add(iid)
                                }
                            }
                            hasNewOpenMrEvent = !changedIids.isEmpty()

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

                            // Prefer the MR whose code SHA actually changed / was newly opened,
                            // not whichever open MR GitLab lists as most recently "updated".
                            def selectedIid = changedIids.max { iid ->
                                def epochText = mrProps["MR_${iid}_UPDATED_EPOCH"] ?: '0'
                                (epochText ==~ /^[0-9]+$/) ? epochText.toLong() : 0L
                            } as String

                            kernelDriverRef = mrProps["MR_${selectedIid}_SOURCE_BRANCH"] ?: env.KERNEL_DRIVER_BRANCH
                            kernelDriverMrIid = selectedIid
                            kernelDriverMrTitle = mrProps["MR_${selectedIid}_TITLE"] ?: ''
                            kernelDriverMrUpdatedAt = mrProps["MR_${selectedIid}_UPDATED_AT"] ?: ''
                            kernelDriverMrUrl = mrProps["MR_${selectedIid}_WEB_URL"] ?: ''
                            mrProps.MR_SHA = mrProps["MR_${selectedIid}_SHA"] ?: ''
                            mrProps.MR_TARGET_BRANCH = mrProps["MR_${selectedIid}_TARGET_BRANCH"] ?: env.KERNEL_DRIVER_BRANCH
                            def targetBranch = (mrProps.MR_TARGET_BRANCH ?: env.KERNEL_DRIVER_BRANCH).trim()
                            def sourceBranch = (kernelDriverRef ?: '').trim()

                            withCredentials([string(credentialsId: env.KERNEL_DRIVER_GITLAB_TOKEN_CRED, variable: 'GITLAB_TOKEN')]) {
                                sh """
                                set -eu
                                python3 - <<'PY'
from urllib.parse import quote
import urllib.request
import os

api = "${KERNEL_DRIVER_GITLAB_API}"
project = "${KERNEL_DRIVER_GITLAB_PROJECT}"
token = os.environ["GITLAB_TOKEN"]
source = ${groovy.json.JsonOutput.toJson(sourceBranch)}
target = ${groovy.json.JsonOutput.toJson(targetBranch)}
url = (
    f"{api}/projects/{project}/repository/compare"
    f"?from={quote(target, safe='')}&to={quote(source, safe='')}"
)
request = urllib.request.Request(url, headers={"PRIVATE-TOKEN": token})
with urllib.request.urlopen(request) as response, open("kernel_driver_mr_compare.json", "wb") as out:
    out.write(response.read())
PY
                                """
                            }
                            def hasCodeDelta = sh(
                                returnStatus: true,
                                script: 'python3 ci/gitlab_mr_has_code_delta.py kernel_driver_mr_compare.json'
                            ) == 0
                            if (!hasCodeDelta) {
                                sh """
                                mkdir -p '${jenkinsHome}/.raid_nvme'
                                printf '%s\\n' '${currentMrSignature}' > '${markerPath}'
                                """
                                currentBuild.result = 'NOT_BUILT'
                                echo "kernel_driver open MR !${selectedIid} has no code delta vs ${targetBranch} (source=${sourceBranch}). Skip smoke tests."
                                return
                            }

                            shouldRunTests = true
                            useQemuVmTarget = true
                            automaticMrTriggered = true
                            triggerSource = 'kernel_driver Merge Request'

                            if (kernelDriverMrIid) {
                                echo "kernel_driver open MR !${kernelDriverMrIid} code changed at ${kernelDriverMrUpdatedAt}: ${kernelDriverMrTitle}"
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
                                def remoteDir = remoteWorkspaceRoot('restore')

                                def restoreSsh = hostSshCmd(ip)

                                echo "[${ip}] stop running test processes"
                                sh """
                                ${restoreSsh} '
                                    pkill -9 -f nvme_raid_test.py 2>/dev/null || true
                                    pkill -2 -f Stress_Monitor/main.py 2>/dev/null || true
                                    pkill -9 -f run_fio.sh 2>/dev/null || true
                                    pkill -9 -f Fio_All.sh 2>/dev/null || true
                                    pkill -9 fio 2>/dev/null || true
                                ' || true
                                """

                                echo "[${ip}] deploy restore scripts"
                                sh "${restoreSsh} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'"
                                copyWorkspaceToRemote(ip, remoteDir, env.TARGET_USER, env.SSH_OPTS)

                                echo "[${ip}] execute restore"
                                sh """
                                ${restoreSsh} '
                                    cd ${remoteDir}/IO_Stress && bash ./Fio_All.sh -i restore || true
                                '
                                """

                                echo "[${ip}] clean temporary directory"
                                sh "${restoreSsh} 'rm -rf ${remoteDir}' || true"
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

                    def dpraidReady = sh(
                        script: "test -x '${raidCliDpraidPathForRun}'; echo \$?",
                        returnStdout: true
                    ).trim() == '0'
                    def draidTreeReady = sh(
                        script: "test -d kernel_driver/drivers/draid && test -f kernel_driver/drivers/draid/Makefile; echo \$?",
                        returnStdout: true
                    ).trim() == '0'

                    if (!dpraidReady || !draidTreeReady) {
                        def reason = !dpraidReady
                            ? "dpraid artifact missing or not executable: ${raidCliDpraidPathForRun}"
                            : 'kernel_driver/drivers/draid tree or Makefile missing'
                        echo "ERROR: Run Tests preflight failed: ${reason}"
                        for (int i = 0; i < targetIPs.size(); i++) {
                            def ip = targetIPs[i]
                            markSmokeEnvironmentPrepareFailed(ip, "environment_prepare_${ip}.log", reason)
                        }
                        error "Run Tests preflight failed: ${reason}"
                    }

                    env.TEST_EXECUTION_ATTEMPTED = 'true'
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
                                runSmokeNodeTest(ip, raidCliDpraidPathForRun)
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

                // Node-level reports only; skip leftover per-item report_<case>.xml files.
                junit testResults: 'report_*.*.*.*.xml,report_*_physical.xml', allowEmptyResults: true

                allure(
                    includeProperties: true,
                    jdk: '',
                    reportName: 'TEST REPORT',
                    results: [[path: 'allure-results']]
                )

                archiveArtifacts artifacts: 'jenkins_console.log, test_execution_*.log, environment_prepare_*.log, allure-results/monitor_log_*.tar.gz', allowEmptyArchive: true

                def metricsOutput = sh(script: "python3 ci/report_metrics.py", returnStdout: true).trim()
                sh 'python3 ci/extract_failure_summary.py --output failure_summary.txt || true'

                def metrics = metricsOutput.split(' ')
                def total = metrics[0].toInteger()
                def failed = metrics[1].toInteger()
                def errors = metrics[2].toInteger()
                def skipped = metrics[3].toInteger()
                def reportKind = metrics.size() > 4 ? metrics[4] : 'tests'
                def hasFailureSummary = fileExists('failure_summary.txt') && readFile('failure_summary.txt').trim()

                def startStr = new Date(currentBuild.startTimeInMillis).format('yyyy-MM-dd HH:mm:ss')
                def endStr = new Date().format('yyyy-MM-dd HH:mm:ss')
                def ipListStr = targetIPs.join(', ')
                def buildResult = currentBuild.currentResult ?: currentBuild.result ?: 'UNKNOWN'
                def testAttempted = (env.TEST_EXECUTION_ATTEMPTED == 'true')
                if (total == 0 && !hasFailureSummary) {
                    echo "Skip Feishu notification: no reportable test or environment prepare result was generated in this build. testAttempted=${testAttempted}, result=${buildResult}"
                    return
                }
                if (total == 0 && hasFailureSummary) {
                    // Prefer countable env/execution items from report_metrics; only force a
                    // single infra error when logs could not be turned into metrics.
                    reportKind = 'infra'
                    total = 1
                    errors = Math.max(errors, 1)
                    echo "Feishu notification will use a fallback infra count because no countable results were generated."
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
                    "REPORT_KIND=${reportKind}",
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
                    "JOB_NAME=${env.JOB_NAME}",
                    "BUILD_NUMBER=${env.BUILD_NUMBER}",
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
