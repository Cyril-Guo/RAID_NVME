pipeline {
    agent any

    environment {
        FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/17fe4cfd-5e49-4ceb-b8c4-f002d74340ee'
    }

    stages {
        stage('Prepare & Test') {
            steps {
                cleanWs()
                checkout scm
                sh '''
                pip install -r requirements.txt
                mkdir -p allure-results
                
                # 1. 注入环境信息 (OS 位于顶部)
                {
                  echo "OS=$(grep PRETTY_NAME /etc/os-release | cut -d'=' -f2 | tr -d '\"')"
                  echo "Kernel=$(uname -r)"
                  echo "Host=$(hostname)"
                  echo "NVMe_Count=$(ls /dev/nvme*n1 2>/dev/null | wc -l)"
                } > allure-results/environment.properties

                # 2. 强制报告 UI 为英文
                cat > allure-results/custom.js << 'EOF'
(function() {
    if (localStorage.getItem('allure2locale') !== 'en') {
        localStorage.setItem('allure2locale', 'en');
        window.location.reload();
    }
})();
EOF

                # 3. 执行 FIO 测试
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
                // 修复 sudo 产生的权限问题
                sh 'sudo chown -R jenkins:jenkins . || true'

                // 生成 Allure 报告
                allure(
                    includeProperties: true,
                    jdk: '',
                    results: [[path: 'allure-results']]
                )

                // 归档执行日志
                archiveArtifacts artifacts: 'test_execution.log', allowEmptyArchive: true

                // 获取测试指标 (无需 Python 解析 XML)
                def testAction = currentBuild.rawBuild.getAction(hudson.tasks.test.AbstractTestResultAction.class)
                int total  = testAction ? testAction.totalCount : 0
                int failed = testAction ? testAction.failCount : 0
                int passed = total - failed - (testAction ? testAction.skipCount : 0)
                def passRate = total > 0 ? String.format("%.1f%%", (passed / (double)total) * 100) : "0%"
                def statusColor = (failed == 0 && total > 0) ? "blue" : "red"

                // 飞书精简版通知
                def payload = """
                {
                    "msg_type": "interactive",
                    "card": {
                        "header": {
                            "title": { "tag": "plain_text", "content": "📊 NVMe 测试报告 - #${env.BUILD_NUMBER}" },
                            "template": "${statusColor}"
                        },
                        "elements": [
                            {
                                "tag": "div",
                                "fields": [
                                    { "is_short": true, "text": { "tag": "lark_md", "content": "**通过/总数:** ${passed}/${total}" } },
                                    { "is_short": true, "text": { "tag": "lark_md", "content": "**通过率:** ${passRate}" } }
                                ]
                            },
                            {
                                "tag": "action",
                                "actions": [{
                                    "tag": "button",
                                    "text": { "tag": "plain_text", "content": "查看 Allure 详情" },
                                    "url": "${env.BUILD_URL}allure/",
                                    "type": "primary"
                                }]
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
