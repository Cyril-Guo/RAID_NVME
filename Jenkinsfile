pipeline {
    // 在 Jenkins 环境下运行
    agent any

    environment {
        // 【配置项】请在此处填入你飞书群机器人的 Webhook 地址
        FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/17fe4cfd-5e49-4ceb-b8c4-f002d74340ee'
    }

    stages {
        stage('Checkout') {
            steps {
                // 此处 Jenkins 会自动从 git@github.com:Cyril-Guo/RAID_NVME.git 拉取代码
                echo '正在拉取代码...'
            }
        }

        stage('Install Dependencies') {
            steps {
                // 安装项目所需的 Python 依赖
                sh 'pip install -r requirements.txt'
            }
        }

        stage('Run Tests') {
            steps {
                // 运行 Pytest：生成 Allure 数据、JUnit XML 报告，并将控制台完整输出记录到日志文件
                // 增加 "|| true" 确保测试失败时流水线不立即中断，以便执行 post 中的报告生成和通知
                sh 'pytest --alluredir=./allure-results --junitxml=report.xml > test_execution.log 2>&1 || true'
            }
        }
    }

    post {
        always {
            // 发布 JUnit 结果
            junit 'report.xml'

            // 生成 Allure HTML 测试报告
            allure includeProperties: false, jdk: '', results: [[path: 'allure-results']]

            // 归档测试日志，方便开发负责人直接下载
            archiveArtifacts artifacts: 'test_execution.log', allowEmptyArchive: true

            script {
                // 1. 使用 Python 解析 XML 报告中的核心指标
                def total = sh(script: "python3 -c \"import xml.etree.ElementTree as ET; tree = ET.parse('report.xml'); root = tree.getroot(); print(root.attrib.get('tests', 0))\"", returnStdout: true).trim()
                def failed = sh(script: "python3 -c \"import xml.etree.ElementTree as ET; tree = ET.parse('report.xml'); root = tree.getroot(); print(root.attrib.get('failures', 0))\"", returnStdout: true).trim()
                def errors = sh(script: "python3 -c \"import xml.etree.ElementTree as ET; tree = ET.parse('report.xml'); root = tree.getroot(); print(root.attrib.get('errors', 0))\"", returnStdout: true).trim()
                def skipped = sh(script: "python3 -c \"import xml.etree.ElementTree as ET; tree = ET.parse('report.xml'); root = tree.getroot(); print(root.attrib.get('skipped', 0))\"", returnStdout: true).trim()
                
                // 计算通过数和通过率
                int t = total.toInteger()
                int f = failed.toInteger()
                int e = errors.toInteger()
                int s = skipped.toInteger()
                int passed = t - f - e - s
                def passRate = t > 0 ? String.format("%.1f%%", (passed / (double)t) * 100) : "0%"

                // 2. 根据是否有失败来决定卡片颜色（蓝色代表成功，红色代表有错误）
                def colorTemplate = (f + e == 0) ? "blue" : "red"

                // 3. 构造飞书交互式卡片 JSON 载荷
                def payload = """
                {
                    "msg_type": "interactive",
                    "card": {
                        "config": { "wide_screen_mode": true },
                        "header": {
                            "title": { "tag": "plain_text", "content": "🔔 RAID_NVME 自动化测试提醒 - #${env.BUILD_NUMBER}" },
                            "template": "${colorTemplate}"
                        },
                        "elements": [
                            {
                                "tag": "div",
                                "fields": [
                                    { "is_short": true, "text": { "tag": "lark_md", "content": "**构建分支：**\\n${env.BRANCH_NAME ?: 'dev'}" } },
                                    { "is_short": true, "text": { "tag": "lark_md", "content": "**测试统计：**\\n总数: ${total} | 失败: ${f} | 跳过: ${s}" } },
                                    { "is_short": true, "text": { "tag": "lark_md", "content": "**通过率：**\\n${passRate}" } }
                                ]
                            },
                            {
                                "tag": "action",
                                "actions": [
                                    {
                                        "tag": "button",
                                        "text": { "tag": "plain_text", "content": "Jenkins 详情 (Allure)" },
                                        "url": "${env.BUILD_URL}allure/",
                                        "type": "primary"
                                    }
                                ]
                            }
                        ]
                    }
                }
                """
                
                // 4. 通过 curl 发送卡片到飞书
                sh "curl -X POST -H 'Content-Type: application/json' -d '${payload}' ${env.FEISHU_WEBHOOK}"
            }
        }
    }
}
