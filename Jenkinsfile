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

                // ===== 强制修改 Allure Report HTML（关键）=====
                sh '''
                REPORT_DIR=$(ls -d */allure-report 2>/dev/null | head -n 1)

                if [ -d "$REPORT_DIR" ]; then
                  INDEX_HTML="$REPORT_DIR/index.html"

                  # 注入 JS + CSS
                  sed -i '/<\\/body>/i \
<script> \
document.addEventListener("DOMContentLoaded", function () { \
  /* 隐藏左侧【类别】 */ \
  document.querySelectorAll("li, a, span, div").forEach(function(el){ \
    if(el.textContent && el.textContent.trim()==="类别"){ \
      var p = el.closest("li") || el.closest("a") || el.parentElement; \
      if(p) p.style.display="none"; \
    } \
  }); \
  /* 隐藏 Overview【类别】卡片 */ \
  document.querySelectorAll(".widget").forEach(function(w){ \
    var t=w.querySelector(".widget__title"); \
    if(t && t.textContent.trim().startsWith("类别")){ \
      w.style.display="none"; \
    } \
  }); \
  /* 测试套 -> 测试日志 */ \
  document.querySelectorAll("*").forEach(function(el){ \
    if(el.childNodes.length===1 && el.textContent){ \
      var tx=el.textContent.trim(); \
      if(tx==="测试套"){ el.textContent="测试日志"; } \
      else if(tx.startsWith("测试套")){ el.textContent=tx.replace("测试套","测试日志"); } \
    } \
  }); \
}); \
</script> \
<style> \
/* 双保险：防止残留 */ \
</style>' "$INDEX_HTML"
                fi
                '''

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
                    "header": {
                      "title": { "tag": "plain_text", "content": "📊 RAID_NVME 测试报告 - #${env.BUILD_NUMBER}" },
                      "template": "${statusColor}"
                    },
                    "elements": [
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

