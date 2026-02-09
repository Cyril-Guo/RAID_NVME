pipeline {
    // 在 Jenkins 环境下运行
    agent any

    stages {
        stage('Checkout') {
            steps {
                // 此处 Jenkins 会根据你的项目配置自动从 git@github.com:Cyril-Guo/RAID_NVME.git 拉取代码
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
                // 运行 Pytest 并同时生成 Allure 原始数据、JUnit XML 报告，并将控制台输出记录到日志文件
                // 增加 "> test_execution.log 2>&1" 是为了捕获完整的运行日志供开发查看
                sh 'pytest --alluredir=./allure-results --junitxml=report.xml > test_execution.log 2>&1'
            }
        }
    }

    post {
        always {
            // 无论测试是否成功，都发布 JUnit 结果
            junit 'report.xml'

            // 生成并发布 Allure HTML 测试报告
            // 执行后，你可以在 Jenkins 项目页面左侧看到 "Allure Report" 按钮
            allure includeProperties: false, jdk: '', results: [[path: 'allure-results']]

            // 将测试日志文件归档，方便开发负责人在构建页面直接点击下载
            archiveArtifacts artifacts: 'test_execution.log', allowEmptyArchive: true
        }
    }
}
