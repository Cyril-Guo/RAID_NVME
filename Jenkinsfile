def targetIPs = []
def kernelDriverCommit = ''
def shouldRunTests = true

def copyWorkspaceToRemote(ip, remoteDir, targetUser) {
    sh """
    tar \
      --exclude='./.git' \
      --exclude='./kernel_driver' \
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
    }

    triggers {
        pollSCM('H/15 * * * *')
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
    }

    stages {
        stage('Prepare Workspace') {
            steps {
                cleanWs()

                checkout scm: scm, poll: false, changelog: false

                script {
                    if (!params.RESTORE) {
                        checkout scm: [
                            $class: 'GitSCM',
                            branches: [[name: "*/${env.KERNEL_DRIVER_BRANCH}"]],
                            userRemoteConfigs: [[
                                url: env.KERNEL_DRIVER_REPO,
                                credentialsId: env.KERNEL_DRIVER_CRED
                            ]],
                            extensions: [
                                [$class: 'RelativeTargetDirectory', relativeTargetDir: 'kernel_driver'],
                                [$class: 'CloneOption', shallow: true, depth: 1, noTags: true, timeout: 30]
                            ]
                        ], poll: true, changelog: true

                        kernelDriverCommit = sh(
                            script: "git -C kernel_driver rev-parse --short HEAD 2>/dev/null || echo unknown",
                            returnStdout: true
                        ).trim()
                        echo "kernel_driver(${env.KERNEL_DRIVER_BRANCH}) commit: ${kernelDriverCommit}"

                        def scmTriggered = currentBuild.getBuildCauses('hudson.triggers.SCMTrigger$SCMTriggerCause').size() > 0
                        def kernelDriverChanged = currentBuild.changeSets.any { changeSet ->
                            changeSet.items && changeSet.items.length > 0
                        }

                        if (scmTriggered && !kernelDriverChanged) {
                            shouldRunTests = false
                            currentBuild.result = 'NOT_BUILT'
                            echo 'SCM build was not caused by kernel_driver changes. Skip NVMe RAID smoke tests.'
                        }
                    }
                }

                script {
                    if (!shouldRunTests && !params.RESTORE) {
                        echo 'Skip target node loading because this SCM build has no kernel_driver changes.'
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
                    echo 'This stage is still a placeholder. kernel_driver is only polled and its commit is displayed.'
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
                                    python3 -m pip install -r requirements.txt --break-system-packages || python3 -m pip install -r requirements.txt
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
                                    script: """
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
                    echo 'No kernel_driver change detected. Nothing to report.'
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

                archiveArtifacts artifacts: 'test_execution_*.log', allowEmptyArchive: true

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

                def payload = """
                {
                  "msg_type": "interactive",
                  "card": {
                    "config": { "wide_screen_mode": true },
                    "header": {
                      "title": { "tag": "plain_text", "content": "NVMe_RAID(F6501) Test Report" },
                      "template": "${statusColor}"
                    },
                    "elements": [
                      {
                        "tag": "div",
                        "fields": [
                          { "is_short": true, "text": { "tag": "lark_md", "content": "**用户名:** dapustor" } },
                          { "is_short": true, "text": { "tag": "lark_md", "content": "**密码:** Admin@9000" } },
                          { "is_short": false, "text": { "tag": "lark_md", "content": "**时间周期:**\\n${startStr} ~ ${endStr}" } },
                          { "is_short": false, "text": { "tag": "lark_md", "content": "**并发节点:**\\n${ipListStr}" } },
                          { "is_short": false, "text": { "tag": "lark_md", "content": "**被测驱动(kernel_driver):**\\n${kernelDriverCommit ?: 'unknown'}" } }
                        ]
                      },
                      {
                        "tag": "div",
                        "text": {
                          "tag": "lark_md",
                          "content": "通过 **${passed}**  失败 **${failed}**  错误 **${errors}**  Total: **${total}**\\n执行率: ${execRate}   通过率: <font color=\\"${fontColor}\\">${passRate}</font>"
                        }
                      },
                      {
                        "tag": "action",
                        "actions": [
                          {
                            "tag": "button",
                            "text": { "tag": "plain_text", "content": "查看详情" },
                            "url": "${env.BUILD_URL}allure/",
                            "type": "primary"
                          }
                        ]
                      }
                    ]
                  }
                }
                """

                writeFile file: 'feishu_payload.json', text: payload
                sh "curl -s -X POST -H 'Content-Type: application/json' -d @feishu_payload.json ${env.FEISHU_WEBHOOK}"
            }
        }
    }
}
