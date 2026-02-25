def targetIPs = []

pipeline {
    agent any

    environment {
        FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/17fe4cfd-5e49-4ceb-b8c4-f002d74340ee'
        TARGET_USER = 'root' 
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
                                def remoteDir = "/tmp/jenkins_fio_${env.BUILD_NUMBER}"
                                sh "ssh ${env.TARGET_USER}@${ip} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'"
                                sh "scp -r * ${env.TARGET_USER}@${ip}:${remoteDir}/"
                                sh "ssh ${env.TARGET_USER}@${ip} 'cd ${remoteDir} && pip install -r requirements.txt'"
                                
                                // 收集环境信息
                                sh """
                                ssh ${env.TARGET_USER}@${ip} '
                                    cd ${remoteDir}
                                    mkdir -p allure-results
                                    {
                                        echo "Node_${ip}_Host=\$(hostname)"
                                        echo "Node_${ip}_Kernel=\$(uname -r)"
                                        echo "Node_${ip}_NVMe_Count=\$(ls /dev/nvme*n1 2>/dev/null | wc -l)"
                                    } > allure-results/environment_${ip}.properties
                                '
                                """
                                
                                // 运行 FIO
                                sh """
                                ssh ${env.TARGET_USER}@${ip} "cd ${remoteDir} && ALLOW_DESTRUCTIVE_FIO=${env.ALLOW_DESTRUCTIVE_FIO} sudo pytest test_fio.py --alluredir=./allure-results --junitxml=report.xml -o log_cli=true -o log_cli_level=INFO || true" 2>&1 | awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), \$0 }' | tee test_execution_${ip}.log
                                """
                                
                                // 回传数据
                                sh """
                                mkdir -p allure-results
                                scp -r ${env.TARGET_USER}@${ip}:${remoteDir}/allure-results/* ./allure-results/ || true
                                scp ${env.TARGET_USER}@${ip}:${remoteDir}/report.xml ./report_${ip}.xml || true
                                """
                            }
                        }
                    }
                    parallel parallelTasks
                }
            }
        }

        stage('后期处理：UI 样式强行补丁') {
            steps {
                sh '''
                cat allure-results/environment_*.properties > allure-results/environment.properties 2>/dev/null || true
                rm -f allure-results/environment_*.properties

                # ---------- custom.css (使用最强优先级隐藏类别) ----------
                cat > allure-results/custom.css << 'EOF'
/* 隐藏左侧侧边栏按钮 */
[data-id='categories'], .side-menu__item_type_categories { 
    display: none !important; 
}

/* 隐藏首页右下角的 Categories/类别 挂件 */
.widget_type_categories, [data-id='categories'] { 
    display: none !important; 
}

/* 针对某些 Allure 版本的通用卡片选择器 */
.widgets-grid > div:has(.widget__title:contains("Categories")),
.widgets-grid > div:has(.widget__title:contains("类别")) {
    display: none !important;
}
EOF

                # ---------- custom.js ----------
                cat > allure-results/custom.js << 'EOF'
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('*').forEach(el => {
    if (el.childNodes.length === 1 && el.innerText && el.innerText.trim() === '测试套') {
      el.innerText = '测试日志';
    }
  });
});
EOF
                '''
            }
        }
    }

    post {
        always {
            script {
                sh 'sudo chown -R jenkins:jenkins . || true'
                junit testResults: 'report_*.xml', allowEmptyResults: true

                // 1. 修改 Allure 标题为 "TEST REPORT"
                allure(
                    includeProperties: true,
                    jdk: '',
                    reportName: 'TEST REPORT', 
                    results: [[path: 'allure-results']]
                )

                archiveArtifacts artifacts: 'test_execution_*.log', allowEmptyArchive: true

                def getMetric = { attr ->
                    return sh(script: """
                        python3 - << 'EOF'
import xml.etree.ElementTree as ET
import glob
val = 0
files = glob.glob('report_*.xml')
for f in files:
    try:
        t = ET.parse(f).getroot()
        val += int(t.attrib.get('${attr}') or sum(int(s.get('${attr}',0)) for s in t.findall('.//testsuite')))
    except: pass
print(val)
EOF
                    """, returnStdout: true).trim()
                }

                def total   = getMetric('tests').toInteger()
                def failed  = getMetric('failures').toInteger()
                def errors  = getMetric('errors').toInteger()
                def passed  = total - failed - errors - getMetric('skipped').toInteger()
                def execRate = total > 0 ? String.format("%.2f%%", (total / (double) total) * 100) : "0%"
                def passRate = total > 0 ? String.format("%.1f%%", (passed / (double) total) * 100) : "0%"
                def startStr = new Date(currentBuild.startTimeInMillis).format("yyyy-MM-dd HH:mm:ss")
                def endStr   = new Date().format("yyyy-MM-dd HH:mm:ss")
                def statusColor = (failed + errors == 0 && total > 0) ? "blue" : "red"

                // 2. 修改飞书标题为 "RAID_NVME 测试报告" 并修改按钮文案
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
                          { "is_short": false, "text": { "tag": "lark_md", "content": "**测试规模：** ${targetIPs.size()} 台并行\\n**目标 IP：** ${targetIPs.join(', ')}" } },
                          { "is_short": false, "text": { "tag": "lark_md", "content": "**时间周期：**\\n${startStr} ~ ${endStr}" } }
                        ]
                      },
                      {
                        "tag": "div",
                        "text": {
                          "tag": "lark_md",
                          "content": "✔️ **${passed}** ❌ **${failed}** ⛔ **${errors}** Total: **${total}**\\n执行率：${execRate}   通过率：<font color='${statusColor == 'blue' ? 'green' : 'red'}'>${passRate}</font>"
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
                sh "curl -s -X POST -H 'Content-Type: application/json' -d '${payload}' ${env.FEISHU_WEBHOOK}"
            }
        }
    }
}
