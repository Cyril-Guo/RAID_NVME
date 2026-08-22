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
// Only env_prepare pulls latest raid_cli+kernel_driver and stages dpraid for DUT refresh.
def needsPhysicalIoDriverPrep = false
def selectedTestItems = []

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

// DUT layout: /root/Cyril/Jenkins/<JOB>/<BRANCH>/<build|restore>-<N>
// Keeps CI/SMOKE, branches, and builds from mixing in one flat directory.
def remoteWorkspaceRoot(kind = 'build') {
    def job = sanitizePathSegment(env.JOB_BASE_NAME ?: env.JOB_NAME ?: 'job')
    def branch = sanitizePathSegment(resolveRaidNvmeBranch())
    def prefix = (kind == 'restore') ? 'restore' : 'build'
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

pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        skipDefaultCheckout()
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
        string(
            name: 'MANUAL_MR_IID',
            defaultValue: '',
            trim: true,
            description: 'Optional: kernel_driver merge request IID, for example 141. Takes priority over MANUAL_KERNEL_DRIVER_REF.'
        )
        string(
            name: 'MANUAL_KERNEL_DRIVER_REF',
            defaultValue: '',
            trim: true,
            description: 'Optional: kernel_driver branch to test. Empty means main; ignored when MANUAL_MR_IID is set.'
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
        TEST_IDLE_TIMEOUT_MINUTES = '90'
        ENVIRONMENT_STEP_TIMEOUT_MINUTES = '15'
        TEST_EXECUTION_ATTEMPTED = 'false'
        SSH_OPTS = '-o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ConnectTimeout=15'

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
                        shouldRunTests = true
                        def selectedRaw = sh(
                            script: '''python3 - <<'PY'
from nvme_raid_test import read_enabled_selection
print(" ".join(read_enabled_selection("test_items.txt")))
PY''',
                            returnStdout: true
                        ).trim()
                        selectedTestItems = selectedRaw ? selectedRaw.split(' ') as List : []
                        needsPhysicalIoDriverPrep = selectedTestItems.contains('env_prepare')
                        echo "Selected test items: ${selectedTestItems}"
                        echo "Pull latest raid_cli/kernel_driver for env_prepare: ${needsPhysicalIoDriverPrep}"

                        if (!needsPhysicalIoDriverPrep) {
                            triggerSource = 'Manual Build'
                            kernelDriverCommit = 'skipped'
                            raidCliCommit = 'skipped'
                            echo 'Skip raid_cli sync and kernel_driver checkout: env_prepare not selected.'
                            if ((params.MANUAL_MR_IID ?: '').trim() || (params.MANUAL_KERNEL_DRIVER_REF ?: '').trim()) {
                                echo 'MANUAL_MR_IID / MANUAL_KERNEL_DRIVER_REF ignored because env_prepare is not selected.'
                            }
                        } else {
                        // CI is manual-only: default kernel_driver/main; optional MANUAL_MR_IID or MANUAL_KERNEL_DRIVER_REF.
                        def raidCliMarkerName = "${env.JOB_NAME}_${env.RAID_CLI_BRANCH}_raid_cli_commit".replaceAll('[^A-Za-z0-9_.-]', '_')
                        def raidCliMarkerPath = "${jenkinsHome}/.raid_nvme/${raidCliMarkerName}.commit"
                        def raidCliWorkDir = "${jenkinsHome}/.raid_nvme/${raidCliMarkerName}.repo"
                        raidCliDpraidPath = "${raidCliWorkDir}/dpraid"
                        def mrProps = [:]
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

                        def manualMrIid = (params.MANUAL_MR_IID ?: '').trim()
                        def manualKernelDriverRef = (params.MANUAL_KERNEL_DRIVER_REF ?: '').trim()
                        syncRaidCli('env_prepare selected')

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
                            triggerSource = 'Manual MR Build'
                            echo "Manual MR build requested. Run tests on kernel_driver !${kernelDriverMrIid} ${kernelDriverRef}."
                        } else {
                            if (manualKernelDriverRef) {
                                if (!(manualKernelDriverRef ==~ '[A-Za-z0-9][A-Za-z0-9._/-]*') ||
                                    manualKernelDriverRef.contains('..') ||
                                    manualKernelDriverRef.endsWith('/')) {
                                    error "MANUAL_KERNEL_DRIVER_REF is not a safe branch name: ${manualKernelDriverRef}"
                                }
                                kernelDriverRef = manualKernelDriverRef
                                triggerSource = 'Manual Branch Build'
                            } else {
                                kernelDriverRef = env.KERNEL_DRIVER_BRANCH
                                triggerSource = 'Manual Build'
                            }
                            echo "Manual build requested. Run tests on kernel_driver/${kernelDriverRef}."
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

                        // Stage dpraid into workspace so deploy packs it for per-case refresh only.
                        sh """
                        set -eu
                        test -x '${raidCliDpraidPath}'
                        mkdir -p artifacts
                        install -m 0755 '${raidCliDpraidPath}' artifacts/dpraid
                        """
                        } // end needsPhysicalIoDriverPrep
                    }
                }

                script {
                    if (!shouldRunTests && !params.RESTORE) {
                        echo 'Skip target node loading because this build is not configured to run tests.'
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
            when { expression { return !params.RESTORE && shouldRunTests && needsPhysicalIoDriverPrep } }
            steps {
                script {
                    echo "kernel_driver commit for this run: ${kernelDriverCommit ?: 'unknown'}"
                    if (kernelDriverMrIid) {
                        echo "kernel_driver MR for this run: !${kernelDriverMrIid} ${kernelDriverMrUrl}"
                    }
                    echo 'kernel_driver/raid_cli were pulled because env_prepare is selected.'
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
                    env.TEST_EXECUTION_ATTEMPTED = 'true'
                    if (needsPhysicalIoDriverPrep) {
                        def jenkinsHome = env.JENKINS_HOME ?: '/var/lib/jenkins'
                        def raidCliMarkerName = "${env.JOB_NAME}_${env.RAID_CLI_BRANCH}_raid_cli_commit".replaceAll('[^A-Za-z0-9_.-]', '_')
                        def raidCliRepoPathForRun = "${jenkinsHome}/.raid_nvme/${raidCliMarkerName}.repo"
                        def raidCliDpraidPathForRun = raidCliDpraidPath ?: "${raidCliRepoPathForRun}/dpraid"

                        sh "test -x '${raidCliDpraidPathForRun}'"
                        sh "test -x artifacts/dpraid"
                        raidCliFullCommit = sh(
                            script: "git -C '${raidCliRepoPathForRun}' rev-parse HEAD 2>/dev/null || echo unknown",
                            returnStdout: true
                        ).trim()
                        raidCliCommit = sh(
                            script: "git -C '${raidCliRepoPathForRun}' rev-parse --short HEAD 2>/dev/null || echo unknown",
                            returnStdout: true
                        ).trim()
                        echo "Use dpraid artifact: ${raidCliDpraidPathForRun} (staged at artifacts/dpraid for env_prepare)"
                        echo "Use raid_cli(${env.RAID_CLI_BRANCH}) commit: ${raidCliCommit}"
                        sh "test -d kernel_driver/drivers/draid && test -f kernel_driver/drivers/draid/Makefile"
                    } else {
                        echo 'Skip dpraid/kernel_driver requirements: env_prepare not selected.'
                    }

                    def parallelTasks = [:]

                    for (int i = 0; i < targetIPs.size(); i++) {
                        def ip = targetIPs[i]

                        parallelTasks["Node_${ip}"] = {
                            stage("Test on ${ip}") {
                                def remoteDir = remoteWorkspaceRoot('build')
                                def envPrepareLog = "environment_prepare_${ip}.log"
                                def targetSsh = hostSshCmd(ip)
                                def targetScp = hostScpCmd()

                                writeFile file: envPrepareLog, text: "[${ip}] Environment_Prepare started\n"
                                echo "[${ip}] remote workspace: ${remoteDir}"

                                echo "[${ip}] deploy workspace"
                                runTimedEnvironmentStep(ip, 'deploy workspace', envPrepareLog, env.ENVIRONMENT_STEP_TIMEOUT_MINUTES, """#!/bin/bash
set -euo pipefail
{
echo "[${ip}] deploy workspace -> ${remoteDir}"
${targetSsh} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'
chmod +x ci/deploy_workspace.sh
NODE_IP='${ip}' \\
TARGET_USER='${env.TARGET_USER}' \\
REMOTE_DIR='${remoteDir}' \\
REMOTE_SSH_COMMAND="${targetSsh}" \\
ci/deploy_workspace.sh
} 2>&1 | tee -a ${envPrepareLog}
""")

                                // draid/dpraid refresh is intentionally NOT done in Jenkins shared prepare.
                                // The env_prepare test case runs ci/prepare_env.sh on the DUT.
                                if (needsPhysicalIoDriverPrep) {
                                    echo "[${ip}] env_prepare selected: skip shared dpraid/draid prepare; case runs prepare_env.sh"
                                    sh "printf '%s\\n' '[${ip}] skip shared install_dpraid/prepare_draid; env_prepare uses ci/prepare_env.sh' >> ${envPrepareLog}"
                                } else {
                                    echo "[${ip}] skip shared dpraid/draid prepare (env_prepare not selected)"
                                    sh "printf '%s\\n' '[${ip}] skip shared install_dpraid/prepare_draid' >> ${envPrepareLog}"
                                }

                                echo "[${ip}] install python dependencies"
                                runTimedEnvironmentStep(ip, 'install python dependencies', envPrepareLog, env.ENVIRONMENT_STEP_TIMEOUT_MINUTES, """#!/bin/bash
set -euo pipefail
{
echo "[${ip}] install python dependencies"
${targetSsh} 'cd ${remoteDir} && chmod +x ci/install_test_dependencies.sh && ci/install_test_dependencies.sh'
} 2>&1 | tee -a ${envPrepareLog}
""")

                                echo "[${ip}] collect environment metadata"
                                runTimedEnvironmentStep(ip, 'collect environment metadata', envPrepareLog, env.ENVIRONMENT_STEP_TIMEOUT_MINUTES, """#!/bin/bash
set -euo pipefail
${targetSsh} 'cd ${remoteDir} && chmod +x ci/collect_environment_metadata.sh && NODE_IP=${ip} REMOTE_DIR=${remoteDir} PREFIX=Node_${ip} ci/collect_environment_metadata.sh'
""")
                                sh "printf '%s\\n' 'ENVIRONMENT_PREPARE_STATUS=passed' >> ${envPrepareLog}"

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
 ci/run_remote_test_and_collect.sh
 """
                                )
                                echo "[${ip}] wait powercycle completion if reboot/dc selected"
                                def powercycleWaitStatus = sh(
                                    returnStatus: true,
                                    script: """#!/bin/bash
 chmod +x ci/wait_powercycle_completion.sh
 NODE_IP='${ip}' \
 TARGET_USER='${env.TARGET_USER}' \
 REMOTE_DIR='${remoteDir}' \
 REMOTE_SSH_COMMAND="${targetSsh}" \
 TEST_ITEMS_FILE='test_items.txt' \
 ci/wait_powercycle_completion.sh
 """
                                )
                                // Prefer the pytest/collection failure so fail-fast is not masked by
                                // powercycle wait when reboot/dc never started.
                                if (testStatus != 0) {
                                    error "[${ip}] nvme_raid_test.py or report collection failed with exit code ${testStatus}"
                                }
                                if (powercycleWaitStatus != 0) {
                                    error "[${ip}] powercycle completion wait failed with exit code ${powercycleWaitStatus}"
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
                    echo 'No test run was requested. Nothing to report.'
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
                junit testResults: 'report_*.*.*.*.xml', allowEmptyResults: true

                allure(
                    includeProperties: true,
                    jdk: '',
                    reportName: 'TEST REPORT',
                    results: [[path: 'allure-results']]
                )

                archiveArtifacts artifacts: 'jenkins_console.log, test_execution_*.log, environment_prepare_*.log, allure-results/monitor_log_*.tar.gz', allowEmptyArchive: true

                def metricsOutput = sh(script: "python3 ci/report_metrics.py", returnStdout: true).trim()
                sh 'python3 ci/extract_failure_summary.py --output failure_summary.txt || true'

                def metrics = metricsOutput ? metricsOutput.split(/\s+/) : [] as String[]
                def total = 0
                def failed = 0
                def errors = 0
                def skipped = 0
                def reportKind = 'empty'
                if (metrics.size() >= 4) {
                    try {
                        total = metrics[0].toInteger()
                        failed = metrics[1].toInteger()
                        errors = metrics[2].toInteger()
                        skipped = metrics[3].toInteger()
                        reportKind = metrics.size() > 4 ? metrics[4] : 'tests'
                    } catch (Exception parseEx) {
                        echo "WARN: failed to parse report_metrics output '${metricsOutput}': ${parseEx}"
                        total = 0
                        failed = 0
                        errors = 0
                        skipped = 0
                        reportKind = 'empty'
                    }
                } else {
                    echo "WARN: unexpected report_metrics output '${metricsOutput}'"
                }
                def hasFailureSummary = fileExists('failure_summary.txt') && readFile('failure_summary.txt').trim()

                def startStr = new Date(currentBuild.startTimeInMillis).format('yyyy-MM-dd HH:mm:ss')
                def endStr = new Date().format('yyyy-MM-dd HH:mm:ss')
                def ipListStr = targetIPs.join(', ')
                def buildResult = currentBuild.currentResult ?: currentBuild.result ?: 'UNKNOWN'
                // If JUnit stayed green but logs already captured hard FIO/env failures,
                // force Jenkins + Feishu BUILD_RESULT to FAILURE before payload generation.
                if (hasFailureSummary && buildResult in ['SUCCESS', 'UNKNOWN', '']) {
                    def summaryLower = readFile('failure_summary.txt').toLowerCase()
                    def hardMarkers = [
                        'fio command failed',
                        'fio stage failed',
                        'fio stage abort',
                        'mix_fail_on_any=yes, fail',
                        'idle watchdog',
                        'environment_prepare_status=failed',
                        'test_execution_status=failed',
                        'traceback',
                        'assertionerror',
                    ]
                    if (hardMarkers.any { summaryLower.contains(it) }) {
                        echo "Hard failure summary detected; override BUILD_RESULT ${buildResult} -> FAILURE for Feishu card"
                        currentBuild.result = 'FAILURE'
                        buildResult = 'FAILURE'
                        if (failed + errors == 0) {
                            errors = Math.max(errors, 1)
                            if (total <= 0) {
                                total = 1
                                reportKind = 'infra'
                            }
                        }
                    }
                }
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
                    sh "curl -fsS -X POST -H 'Content-Type: application/json' -d @feishu_payload.json ${env.FEISHU_WEBHOOK}"
                }
            }
        }
    }
}
