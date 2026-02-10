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

        stage('Prepare Allure Environment Info & UI') {
            steps {
                sh '''
                mkdir -p allure-results

                # 环境信息
                {
                  echo "Host=$(hostname)"
                  echo "Kernel=$(uname -r)"
                  echo "NVMe_Count=$(ls /dev/nvme*n1 2>/dev/null | wc -l)"
                } > allure-results/environment.properties

                # UI 定制（隐藏 Categories）
                cat > allure-results/custom.css << 'EOF'
                .side-menu__item[data-id="categories"] {
                  display: none !important;
                }
                .widget-categories {
                  display: none !important;
                }
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

                allure(
                    includeProperties: true,
                    jdk: '',
                    reportName: 'TestReport',
                    results: [[path: 'allure-results']]
                )

                archiveArtifacts artifacts: 'test_execution.log', allowEmptyArchive: true

                // ===== 统计 =====
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
                def passed  = total - failed - errors - skipped

                def startStr = new Date(currentBuild.startTimeInMillis).format("yyyy-MM-dd HH:mm:ss")
                def endStr   = new Date().format("yyyy-MM-dd HH:mm:ss")
                def statusColor = (failed + errors == 0 && total > 0) ? "blue" : "red"

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
                        "tag": "action",
                        "actions": [
                          {
                            "tag": "button",
                            "text": { "tag": "plain_text", "content": "查看 Allure 报告" },
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

