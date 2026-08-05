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
    }

    environment {
        FEISHU_WEBHOOK = credentials('feishu-webhook')
        TARGET_USER = 'root'
        ALLOW_DESTRUCTIVE_FIO = '1'
        TEST_IDLE_TIMEOUT_MINUTES = '15'
        ENVIRONMENT_STEP_TIMEOUT_MINUTES = '15'
        TEST_EXECUTION_ATTEMPTED = 'false'
        SSH_OPTS = '-o StrictHostKeyChecking=no -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ConnectTimeout=15'

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
                        shouldRunTests = true
                        syncRaidCli('manual CI build')

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
                                def targetSsh = "ssh ${env.SSH_OPTS} ${env.TARGET_USER}@${ip}"
                                def targetScp = "scp ${env.SSH_OPTS}"

                                writeFile file: envPrepareLog, text: "[${ip}] Environment_Prepare started\n"

                                echo "[${ip}] deploy workspace"
                                runTimedEnvironmentStep(ip, 'deploy workspace', envPrepareLog, env.ENVIRONMENT_STEP_TIMEOUT_MINUTES, """#!/bin/bash
set -o pipefail
{
echo "[${ip}] deploy workspace"
${targetSsh} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'
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
ci/prepare_draid_driver.sh
} 2>&1 | tee -a ${envPrepareLog}
""")

                                echo "[${ip}] install python dependencies"
                                runTimedEnvironmentStep(ip, 'install python dependencies', envPrepareLog, env.ENVIRONMENT_STEP_TIMEOUT_MINUTES, """#!/bin/bash
set -o pipefail
{
echo "[${ip}] install python dependencies"
${targetSsh} 'cd ${remoteDir} && chmod +x ci/install_test_dependencies.sh && ci/install_test_dependencies.sh'
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
 ALLOW_DESTRUCTIVE_FIO='${env.ALLOW_DESTRUCTIVE_FIO}' \
 ci/run_remote_test_and_collect.sh
 """
                                )
                                if (testStatus != 0) {
                                    error "[${ip}] nvme_raid_test.py or report collection failed with exit code ${testStatus}"
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
