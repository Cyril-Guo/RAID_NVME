// 全局变量：存储从 target_ips.txt 读取的 IP 列表
def targetIPs = []

pipeline {
    agent any

    environment {
        // 飞书机器人 Webhook 地址
        FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/17fe4cfd-5e49-4ceb-b8c4-f002d74340ee'
        // 远程登录用户名
        TARGET_USER = 'root' 
        // 解锁破坏性写入测试开关 (1为开启，注意这会清空被测非系统盘数据)
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
                                def remoteDir = "/tmp/jenkins_nvme_${env.BUILD_NUMBER}"
                                
                                echo "[${ip}] 1. 部署代码..."
                                sh "ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'"
                                sh "scp -o StrictHostKeyChecking=no -r * ${env.TARGET_USER}@${ip}:${remoteDir}/"
                                
                                echo "[${ip}] 2. 安装 Python 依赖..."
                                sh "ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} 'cd ${remoteDir} && pip3 install -r requirements.txt || pip install -r requirements.txt'"
                                
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
                                // 执行母脚本，将所有输出加时间戳并存入当前 IP 的本地 log 中
                                sh """
                                ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} "cd ${remoteDir} && ALLOW_DESTRUCTIVE_FIO=${env.ALLOW_DESTRUCTIVE_FIO} sudo python3 nvme_raid_test.py || true" 2>&1 | awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), \$0 }' | tee test_execution_${ip}.log
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

        stage('后期处理：UI 样式强行补丁') {
            steps {
                sh '''
                # 合并所有节点的属性文件
                cat allure-results/environment_*.properties > allure-results/environment.properties 2>/dev/null || true
                rm -f allure-results/environment_*.properties

                # ---------- custom.css (彻底隐藏类别模块) ----------
                cat > allure-results/custom.css << 'EOF'
/* 隐藏左侧菜单导航中的类别按钮 */
.side-menu__item[data-id="categories"],
.side-menu__item[data-id="category"],
.side-menu__item_type_categories { 
    display: none !important; 
}

/* 隐藏首页概览中的“类别”及“产品缺陷”模块卡片 */
.widgets-grid .widget_type_categories,
.widget_type_categories,
[data-id='categories'],
.widget:has(.widget__title:contains("Categories")),
.widget:has(.widget__title:contains("类别")),
.widget:has(.widget__title:contains("Product defects")) { 
    display: none !important; 
}
EOF

                # ---------- custom.js (文案替换) ----------
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
                def skipped = getMetric('skipped').toInteger()

                def passed   = total - failed - errors - skipped
                def execRate = total > 0 ? String.format("%.2f%%", ((total - skipped) / (double) total) * 100) : "0%"
                def passRate = total > 0 ? String.format("%.1f%%", (passed / (double) total) * 100) : "0%"

                def startStr = new Date(currentBuild.startTimeInMillis).format("yyyy-MM-dd HH:mm:ss")
                def endStr   = new Date().format("yyyy-MM-dd HH:mm:ss")
                def statusColor = (failed + errors == 0 && total > 0) ? "blue" : "red"

                // ===== 飞书通知发送 =====
                def ipListStr = targetIPs.join(", ")
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
			//{ "is_short": false, "text": { "tag": "lark_md", "content": "**测试规模：** ${targetIPs.size()} 台并行\\n**目标 IP：** ${ipListStr}" } },
                          { "is_short": false, "text": { "tag": "lark_md", "content": "**时间周期：**\\n${startStr} ~ ${endStr}" } 
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
