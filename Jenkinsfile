// 全局变量：存储从 target_ips.txt 读取的 IP 列表
def targetIPs = []

pipeline {
    agent any

    parameters {
        booleanParam(name: 'RUN_REBOOT', defaultValue: true, description: '是否执行 Reboot Powercycle')
        booleanParam(name: 'RUN_DC', defaultValue: true, description: '是否执行 DC Powercycle')
        booleanParam(name: 'RUN_LAWDISK', defaultValue: true, description: '是否执行 Lawdisk Stress')
        booleanParam(name: 'RUN_FILESYSTEM', defaultValue: true, description: '是否执行 Filesystem Stress')
        booleanParam(name: 'RUN_MIX', defaultValue: true, description: '是否执行 Mixed IO Stress')
        booleanParam(name: 'RUN_SPECIFY', defaultValue: false, description: '是否执行 指定盘测试')
        booleanParam(name: 'RUN_RESTORE', defaultValue: false, description: '是否执行 恢复/日志收集')
        booleanParam(name: 'IGNORE_ERROR', defaultValue: false, description: 'MachineCheck 结果不一致时是否继续测试 (非停止模式)')
        
        string(name: 'FIO_CYCLES', defaultValue: '10', description: 'Reboot/DC 测试循环次数 (-l)')
        string(name: 'FIO_DISKS', defaultValue: '', description: '指定磁盘 (例: sdb,sdc)')
    }

    environment {
        // 飞书机器人 Webhook 地址
        FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/17fe4cfd-5e49-4ceb-b8c4-f002d74340ee'
        // 远程登录用户名
        TARGET_USER = 'root' 
        // 解锁破坏性写入测试开关 (可在环境变量或参数中开启)
        ALLOW_DESTRUCTIVE_FIO = '1'
    }

    stages {
        stage('准备阶段：拉取代码与读取 IP') {
            steps {
                cleanWs()
                checkout scm
                
                script {
                    if (fileExists('target_ips.txt')) {
                        def ipContent = readFile('target_ips.txt').trim()
                        targetIPs = ipContent.split('\\r?\\n').findAll { it.trim() != '' && !it.startsWith('#') }
                        
                        if (targetIPs.size() == 0) {
                            error "target_ips.txt 中未发现有效 IP 地址！"
                        }
                        echo "准备对以下节点执行并发测试: ${targetIPs}"
                    } else {
                        error "根目录下缺少 target_ips.txt 文件！"
                    }
                }
            }
        }

        stage('执行阶段：集群并发测试') {
            steps {
                script {
                    def parallelTasks = [:]
                    
                    for (int i = 0; i < targetIPs.size(); i++) {
                        def ip = targetIPs[i] 
                        
                        parallelTasks["Node_${ip}"] = {
                            stage("Test on ${ip}") {
                                def remoteDir = "/root/jenkins_nvme_${env.BUILD_NUMBER}"
                                
                                echo "[${ip}] 1. 部署代码..."
                                sh "ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'"
                                sh "scp -o StrictHostKeyChecking=no -r * ${env.TARGET_USER}@${ip}:${remoteDir}/"
                                
                                echo "[${ip}] 2. 安装 Python 依赖..."
                                sh "ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} 'cd ${remoteDir} && (pip3 install -r requirements.txt --break-system-packages || pip install -r requirements.txt --break-system-packages)'"
                                
                                echo "[${ip}] 3. 获取硬件环境信息..."
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
                                
                                echo "[${ip}] 4. 运行母测试脚本 (nvme_raid_test.py)..."
                                // 将所有勾选参数和配置项透传给远程脚本
                                sh """
                                ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} \"
                                    cd ${remoteDir} && \
                                    ALLOW_DESTRUCTIVE_FIO=${env.ALLOW_DESTRUCTIVE_FIO} \
                                    RUN_REBOOT=${params.RUN_REBOOT} \
                                    RUN_DC=${params.RUN_DC} \
                                    RUN_LAWDISK=${params.RUN_LAWDISK} \
                                    RUN_FILESYSTEM=${params.RUN_FILESYSTEM} \
                                    RUN_MIX=${params.RUN_MIX} \
                                    RUN_SPECIFY=${params.RUN_SPECIFY} \
                                    RUN_RESTORE=${params.RUN_RESTORE} \
                                    IGNORE_ERROR=${params.IGNORE_ERROR} \
                                    FIO_CYCLES=${params.FIO_CYCLES} \
                                    FIO_DISKS='${params.FIO_DISKS}' \
                                    sudo -E python3 nvme_raid_test.py || true
                                \" 2>&1 | awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), \$0 }' | tee test_execution_${ip}.log
                                """
                                
                                echo "[${ip}] 5. 回传测试数据..."
                                sh """
                                mkdir -p allure-results
                                scp -o StrictHostKeyChecking=no -r ${env.TARGET_USER}@${ip}:${remoteDir}/allure-results/* ./allure-results/ || true
                                scp -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip}:${remoteDir}/report.xml ./report_${ip}.xml || true
                                """
                            }
                        }
                    }
                    // 触发并发执行所有主机的测试任务
                    parallel parallelTasks
                }
            }
        }

        stage('后期处理：测试环境属性合并') {
            steps {
                sh '''
                # 合并所有节点的属性文件
                cat allure-results/environment_*.properties > allure-results/environment.properties 2>/dev/null || true
                rm -f allure-results/environment_*.properties
                '''
            }
        }
    }

    post {
        always {
            script {
                sh 'sudo chown -R jenkins:jenkins . || true'

                // 聚合 JUnit XML 报告
                junit testResults: 'report_*.xml', allowEmptyResults: true

                // 生成 Allure 报告，并将标题设为 "TEST REPORT"
                allure(
                    includeProperties: true,
                    jdk: '',
                    reportName: 'TEST REPORT', 
                    results: [[path: 'allure-results']]
                )

                // 归档各节点的完整执行日志
                archiveArtifacts artifacts: 'test_execution_*.log', allowEmptyArchive: true

                // ===== 数据汇总统计 (Python) =====
                // 使用一次 Python 执行获取所有统计数据，避免重复启动环境和解析
                def metricsOutput = sh(script: """
                    python3 - << 'EOF'
import xml.etree.ElementTree as ET
import glob

stats = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
files = glob.glob('report_*.xml')
for f in files:
    try:
        t = ET.parse(f).getroot()
        for attr in stats.keys():
            val = int(t.attrib.get(attr) or sum(int(s.get(attr, 0)) for s in t.findall('.//testsuite')))
            stats[attr] += val
    except: pass
print(f"{stats['tests']} {stats['failures']} {stats['errors']} {stats['skipped']}")
EOF
                """, returnStdout: true).trim()

                def metrics = metricsOutput.split(' ')
                def total   = metrics[0].toInteger()
                def failed  = metrics[1].toInteger()
                def errors  = metrics[2].toInteger()
                def skipped = metrics[3].toInteger()

                def passed   = total - failed - errors - skipped
                def execRate = total > 0 ? String.format("%.2f%%", ((total - skipped) / (double) total) * 100) : "0%"
                def passRate = total > 0 ? String.format("%.1f%%", (passed / (double) total) * 100) : "0%"

                def startStr = new Date(currentBuild.startTimeInMillis).format("yyyy-MM-dd HH:mm:ss")
                def endStr   = new Date().format("yyyy-MM-dd HH:mm:ss")
                def statusColor = (failed + errors == 0 && total > 0) ? "blue" : "red"

                // ===== 飞书通知发送 =====
                // 发送时把集群节点 IP 加上
                def ipListStr = targetIPs.join(", ")
                def fontColor = statusColor == 'blue' ? 'green' : 'red'
                
                // 将 payload 写入本地文件进行发送，避免 curl 时终端解析导致引号被错误截断
                def payload = """
                {
                  "msg_type": "interactive",
                  "card": {
                    "config": { "wide_screen_mode": true },
                    "header": {
                      "title": { "tag": "plain_text", "content": "📊 RAID_NVME 测试报告 - #${env.BUILD_NUMBER}" },
                      "template": "${statusColor}"
                    },
                    "elements": [
                      {
                        "tag": "div",
                        "fields": [
                          { "is_short": true, "text": { "tag": "lark_md", "content": "**用户名:** dapustor" } },
                          { "is_short": true, "text": { "tag": "lark_md", "content": "**密码:** Admin@9000" } },
                          { "is_short": false, "text": { "tag": "lark_md", "content": "**时间周期：**\\n${startStr} ~ ${endStr}" } },
                          { "is_short": false, "text": { "tag": "lark_md", "content": "**并发节点：**\\n${ipListStr}" } }
                        ]
                      },
                      {
                        "tag": "div",
                        "text": {
                          "tag": "lark_md",
                          "content": "✔️ **${passed}** ❌ **${failed}** ⛔ **${errors}** Total: **${total}**\\n执行率：${execRate}   通过率：<font color=\\"${fontColor}\\">${passRate}</font>"
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
