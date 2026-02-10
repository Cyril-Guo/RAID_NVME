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
                2>&1 | awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), $0 }' \
                   | tee test_execution.log || true
                '''
            }
        }

        // ✅ 禁用 Categories 数据源（安全）
        stage('Disable Categories Data') {
            steps {
                sh 'echo "[]" > allure-results/categories.json'
            }
        }
    }

    post {
        always {
            script {

                sh 'sudo chown -R jenkins:jenkins . || true'

                junit testResults: 'report.xml', allowEmptyResults: true

                // 生成 Allure 报告
                allure(
                    includeProperties: true,
                    jdk: '',
                    reportName: 'TestReport',
                    results: [[path: 'allure-results']]
                )

                // =================================================
                // ✅ UI Patch：测试套 → 测试日志 + 隐藏 Categories
                // =================================================
                sh '''
                set +e

                REPORT_DIR="$JENKINS_HOME/jobs/$JOB_NAME/builds/$BUILD_NUMBER/allure-report"

                APP_JS="$REPORT_DIR/app.js"
                CSS_FILE="$REPORT_DIR/styles.css"

                # 1️⃣ Suites → 测试日志（安全字符串替换）
                if [ -f "$APP_JS" ]; then
                    sed -i 's/Suites/测试日志/g' "$APP_JS"
                fi

                # 2️⃣ 隐藏 Categories（CSS，不破坏结构）
                if [ -f "$CSS_FILE" ]; then
                    cat >> "$CSS_FILE" << 'EOF'

/* ================================
   Hide Categories (Safe CSS)
   ================================ */
[data-testid="side-menu"] a[href*="categories"] {
    display: none !important;
}

[data-testid="categories"] {
    display: none !important;
}

.categories {
    display: none !important;
}
EOF
                fi
                '''

                archiveArtifacts artifacts: 'test_execution.log', allowEmptyArchive: true

                // ================= 飞书通知 =================
                def payload = """
                {
                  "msg_type": "interactive",
                  "card": {
                    "config": { "wide_screen_mode": true },
                    "header": {
                      "title": { "tag": "plain_text", "content": "🔔【Daily】RaidCard DailyBuild EVT - #${env.BUILD_NUMBER}" },
                      "template": "blue"
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

                sh """
                curl -s -X POST \
                  -H 'Content-Type: application/json' \
                  -d '${payload}' \
                  ${env.FEISHU_WEBHOOK}
                """
            }
        }
    }
}

