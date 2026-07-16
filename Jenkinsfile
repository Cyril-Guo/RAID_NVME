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
def shouldRunTests = false

def copyWorkspaceToRemote(ip, remoteDir, targetUser) {
    sh """
    tar \
      --exclude='./.git' \
      --exclude='./kernel_driver' \
      --exclude='./raid_cli' \
      --exclude='./.pytest_cache' \
      --exclude='./__pycache__' \
      --exclude='./allure-results' \
      --exclude='./report.xml' \
      --exclude='./report_*.xml' \
      --exclude='./test_execution_*.log' \
      --exclude='./feishu_payload.json' \
      -czf - . | ssh -o StrictHostKeyChecking=no ${targetUser}@${ip} 'tar -xzf - -C ${remoteDir}'
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
    }

    environment {
        FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/17fe4cfd-5e49-4ceb-b8c4-f002d74340ee'
        TARGET_USER = 'root'
        ALLOW_DESTRUCTIVE_FIO = '1'

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
                        def mrProps = [:]
                        def currentMrSignature = 'none'
                        def hasNewOpenMrEvent = false
                        def hasRaidCliUpdate = false

                        if (manuallyTriggered) {
                            shouldRunTests = true
                            kernelDriverRef = env.KERNEL_DRIVER_BRANCH
                            echo "Manual build requested. Run smoke tests on kernel_driver/${kernelDriverRef}."
                        } else {
                            def nowEpoch = sh(script: 'date +%s', returnStdout: true).trim().toLong()
                            def lastRaidCliCheck = sh(
                                script: "cat '${raidCliCheckPath}' 2>/dev/null || echo 0",
                                returnStdout: true
                            ).trim()
                            def lastRaidCliEpoch = (lastRaidCliCheck ==~ /^[0-9]+$/) ? lastRaidCliCheck.toLong() : 0L

                            if (nowEpoch - lastRaidCliEpoch >= 1800L) {
                                echo "Check raid_cli(${env.RAID_CLI_BRANCH}) updates on 30-minute interval."
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
                                    script: "test -d '${raidCliWorkDir}/.git'; echo \$?",
                                    returnStdout: true
                                ).trim() != '0'
                                hasRaidCliUpdate = raidCliFullCommit != 'unknown' && (previousRaidCliCommit != raidCliFullCommit || persistentRaidCliMissing)

                                if (hasRaidCliUpdate) {
                                    sh """
                                    set -eu
                                    mkdir -p '${jenkinsHome}/.raid_nvme'
                                    rm -rf '${raidCliWorkDir}.next'
                                    cp -a raid_cli '${raidCliWorkDir}.next'
                                    rm -rf '${raidCliWorkDir}'
                                    mv '${raidCliWorkDir}.next' '${raidCliWorkDir}'
                                    printf '%s\\n' '${raidCliFullCommit}' > '${raidCliMarkerPath}'
                                    """
                                    currentBuild.description = "raid_cli ${raidCliCommit}"
                                    echo "raid_cli(${env.RAID_CLI_BRANCH}) updated on Jenkins server: ${previousRaidCliCommit ?: 'none'} -> ${raidCliFullCommit}"
                                    echo "raid_cli checkout path: ${raidCliWorkDir}"
                                } else {
                                    echo "raid_cli(${env.RAID_CLI_BRANCH}) has no new commit: ${raidCliCommit}"
                                }

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
        f"{mr.get('iid')}:{mr.get('updated_at')}:{mr.get('sha')}"
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
                                ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} '
                                    pkill -9 -f nvme_raid_test.py 2>/dev/null || true
                                    pkill -2 -f Stress_Monitor/main.py 2>/dev/null || true
                                    pkill -9 -f run_fio.sh 2>/dev/null || true
                                    pkill -9 -f Fio_All.sh 2>/dev/null || true
                                    pkill -9 fio 2>/dev/null || true
                                ' || true
                                """

                                echo "[${ip}] deploy restore scripts"
                                sh "ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'"
                                copyWorkspaceToRemote(ip, remoteDir, env.TARGET_USER)

                                echo "[${ip}] execute restore"
                                sh """
                                ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} '
                                    cd ${remoteDir}/IO_Stress && bash ./Fio_All.sh -i restore || true
                                '
                                """

                                echo "[${ip}] clean temporary directory"
                                sh "ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} 'rm -rf ${remoteDir}' || true"
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
                    def parallelTasks = [:]

                    for (int i = 0; i < targetIPs.size(); i++) {
                        def ip = targetIPs[i]

                        parallelTasks["Node_${ip}"] = {
                            stage("Test on ${ip}") {
                                def remoteDir = "/root/Cyril/Jenkins/jenkins_nvme_${env.BUILD_NUMBER}"

                                echo "[${ip}] deploy workspace"
                                sh "ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'"
                                copyWorkspaceToRemote(ip, remoteDir, env.TARGET_USER)

                                echo "[${ip}] install python dependencies"
                                sh """
                                ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} '
                                    cd ${remoteDir}
                                    python3 -m pip --version >/dev/null 2>&1 || python3 -m ensurepip --default-pip >/dev/null 2>&1 || true
                                    python3 -m pip --version >/dev/null 2>&1 || dnf install -y python3-pip >/dev/null 2>&1 || yum install -y python3-pip >/dev/null 2>&1 || apt-get install -y python3-pip >/dev/null 2>&1 || zypper install -y python3-pip >/dev/null 2>&1 || true
                                    if python3 -m pip install --help 2>/dev/null | grep -q -- "--break-system-packages"; then
                                        python3 -m pip install --break-system-packages -r requirements.txt
                                    else
                                        python3 -m pip install -r requirements.txt
                                    fi
                                '
                                """

                                echo "[${ip}] collect environment metadata"
                                sh """
                                ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} '
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
ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} \"
    cd ${remoteDir} && \
    ALLOW_DESTRUCTIVE_FIO=${env.ALLOW_DESTRUCTIVE_FIO} \
    sudo -E python3 nvme_raid_test.py
\" 2>&1 | awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), \$0 }' | tee test_execution_${ip}.log
"""
                                )

                                echo "[${ip}] copy back reports"
                                sh """
                                mkdir -p allure-results
                                rm -rf allure-results-${ip}
                                scp -o StrictHostKeyChecking=no -r ${env.TARGET_USER}@${ip}:${remoteDir}/allure-results ./allure-results-${ip} || true
                                if [ -d allure-results-${ip} ]; then
                                    cp -R allure-results-${ip}/. ./allure-results/ || true
                                    rm -rf allure-results-${ip}
                                fi
                                scp -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip}:${remoteDir}/report.xml ./report_${ip}.xml || true
                                """

                                if (testStatus != 0) {
                                    error "[${ip}] nvme_raid_test.py failed with exit code ${testStatus}"
                                }

                                if (!fileExists("report_${ip}.xml")) {
                                    error "[${ip}] Missing report_${ip}.xml. nvme_raid_test.py did not produce a JUnit report."
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

                archiveArtifacts artifacts: 'test_execution_*.log, allure-results/monitor_log_*.tar.gz', allowEmptyArchive: true

                def metricsOutput = sh(script: """
                    python3 - << 'EOF'
import glob
import xml.etree.ElementTree as ET

stats = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
for path in glob.glob('report_*.xml'):
    try:
        root = ET.parse(path).getroot()
        for attr in stats:
            value = int(root.attrib.get(attr) or sum(int(suite.get(attr, 0)) for suite in root.findall('.//testsuite')))
            stats[attr] += value
    except Exception:
        pass
print(f"{stats['tests']} {stats['failures']} {stats['errors']} {stats['skipped']}")
EOF
                """, returnStdout: true).trim()

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
                def driverLines = []
                if (kernelDriverMrIid) {
                    driverLines << "MR: !${kernelDriverMrIid} ${kernelDriverMrTitle ?: ''}".trim()
                    driverLines << "Source: ${kernelDriverRef ?: 'unknown'}"
                    driverLines << "Updated: ${kernelDriverMrUpdatedAt ?: 'unknown'}"
                } else {
                    driverLines << "Branch: ${kernelDriverRef ?: env.KERNEL_DRIVER_BRANCH}"
                }
                driverLines << "Commit: ${kernelDriverCommit ?: 'unknown'}"

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
                                    [is_short: false, text: [tag: 'lark_md', content: "**触发来源:**\nkernel_driver Merge Request"]],
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
                sh "curl -s -X POST -H 'Content-Type: application/json' -d @feishu_payload.json ${env.FEISHU_WEBHOOK}"
            }
        }
    }
}
