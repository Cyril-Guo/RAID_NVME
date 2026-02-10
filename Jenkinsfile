pipeline {
    agent any

    environment {
        FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/17fe4cfd-5e49-4ceb-b8c4-f002d74340ee'
    }

    stages {

        stage('Clean & Checkout') {
            steps {
                cleanWs()
                checkout scm
            }
        }

        stage('Install Dependencies') {
            steps {
                sh 'pip install -r requirements.txt'
            }
        }

        stage('Prepare Allure Environment Info') {
            steps {
                sh '''
                mkdir -p allure-results
                {
                  echo "Host=$(hostname)"
                  echo "Kernel=$(uname -r)"
                  echo "NVMe_Count=$(ls /dev/nvme*n1 2>/dev/null | wc -l)"
                } > allure-results/environment.properties
                '''
            }
        }

        stage('Prepare Allure UI Patch (CSS + JS)') {
            steps {
                sh '''
                mkdir -p allure-results

                # ---------------- custom.css ----------------
                # 当前 Allure UI 结构下，隐藏类别主要依赖 JS
                cat > allure-results/custom.css << 'EOF'
/* reserved */
EOF

                # ---------------- custom.js ----------------
                cat > allure-results/custom.js << 'EOF'
document.addEventListener('DOMContentLoaded', () => {

  /* =====================================================
   * 1. 隐藏“类别”模块
   *    - 左侧菜单“类别”
   *    - Overview 页面“类别 总共X项 / Product defects”
   * ===================================================== */

  // 左侧菜单：文本精确等于“类别”
  document.querySelectorAll('li, a, div, span').forEach(el => {
    if (el.textContent && el.textContent.trim() === '类别') {
      const item =
        el.closest('li') ||
        el.closest('a') ||
        el.parentElement;
      if (item) {
        item.style.display = 'none';
      }
    }
  });

  // Overview 页面：标题以“类别”开头的整个 widget
  document.querySelectorAll('.widget').forEach(widget => {
    const title = widget.querySelector('.widget__title');
    if (title && title.textContent.trim().startsWith('类别')) {
      widget.style.display = 'none';
    }
  });

  /* =====================================================
   * 2. “测试套” → “测试日志”
   *    - 左侧菜单
   *    - Overview 标题
   *    - 测试套列表标题
   * ===================================================== */

  document.querySelectorAll('*').forEach(el => {
    if (el.childNodes.length === 1 && el.textContent) {
      const text = el.textContent.trim();
      if (text === '测试套') {
        el.textContent = '测试日志';
      } else if (text.startsWith('测试套')) {
        el.textContent = text.replace('测试套', '测试日志');
      }
    }
  });

});
EOF
                '''
            }
        }

        stage('Run FIO Tests') {
            steps {
                sh '''
                sudo pytest test_fio.py \
                  --alluredir=./allure-results \
                  --junitxml=report.xml \
                  -o log_cli=true \
                  -o log_cli_level=INFO \
                2>&1 | awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0 }' | tee test_execution.log || true
                '''
            }
        }
    }

    post {
        always {
            script {

                sh 'sudo chown -R jenkins:jenkins . || true'

                junit testResults: 'report.xml', allowEmptyResults: true

                // ===== Generate Allure Report =====
                allure(
                    includeProperties: true,
                    jdk: '',
                    reportName: 'TestReport',
                    results: [[path: 'allure-results']]
                )

                archiveArtifacts artifacts: 'test_execution.log', allowEmptyArchive: true

                // ===== Metrics =====
                def getMetric = { attr ->
                    def exists = sh(script: "[ -f report.xml ] && echo yes || echo no", returnStdout: true).trim()
                    if (exists == 'no') return "0"
                    return sh(script: """
                        python3 - << 'EOF'
import xml.etree.ElementTree as ET
t = ET.parse('report.xml').getroot()
print(t.attrib.get('${attr}') or sum(int(s.get('${attr}',0)) for s in t.findall('.//testsuite')))
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

                // ===== Feishu Notify =====
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
                          { "is_short": true, "text": { "tag": "lark_md", "content": "**开始时间：**\\n${startStr}" } },
                          { "is_short": true, "text": { "tag": "lark_md", "content": "**结束时间：**\\n${endStr}" } }
                        ]
                      },
                      {
                        "tag": "div",
                        "text": {
                          "tag": "lark_md",
                          "content": "✔️ **${passed}** ❌ **${failed}** ⛔ **${errors}** Total: **${total}**\\n执行率：${execRate}    通过率：<font color='${statusColor == 'blue' ? 'green' : 'red'}'>${passRate}</font>"
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

