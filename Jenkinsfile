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

                // ===== 生成 Allure 报告 =====
                allure(
                    includeProperties: true,
                    jdk: '',
                    reportName: 'TestReport',
                    results: [[path: 'allure-results']]
                )

                // =========================================================
                // ✅ 每次 build 后自动注入 Allure UI Patch（核心）
                // =========================================================
                sh '''
                set -e

                REPORT_DIR="$JENKINS_HOME/jobs/$JOB_NAME/builds/$BUILD_NUMBER/allure-report"
                APP_JS="$REPORT_DIR/app.js"

                if [ -f "$APP_JS" ]; then
                    echo "[INFO] Inject Allure UI Patch: $APP_JS"

                    if ! grep -q "ALLURE_FORCE_UI_PATCH" "$APP_JS"; then
                        cat << 'EOF' >> "$APP_JS"

/* ================= ALLURE_FORCE_UI_PATCH ================= */
(function () {

  function patch() {
    // Suites -> 测试日志
    document.querySelectorAll('a, span, div').forEach(el => {
      if (el.textContent && el.textContent.trim() === 'Suites') {
        el.textContent = '测试日志';
      }
    });

    // 隐藏 Categories 左侧菜单
    document.querySelectorAll('a[href*="categories"]').forEach(el => {
      el.style.display = 'none';
    });

    // 隐藏 Overview 中 Categories 卡片
    document.querySelectorAll('.widget').forEach(w => {
      const title = w.querySelector('.widget__title');
      if (title && /Categories|类别/.test(title.textContent)) {
        w.style.display = 'none';
      }
    });
  }

  // 初次执行
  patch();

  // DOM 变化监听（防止回退）
  const observer = new MutationObserver(() => {
    patch();
  });

  observer.observe(document.body, {
    childList: true,
    subtree: true
  });

})();
 /* ================= END ALLURE_FORCE_UI_PATCH ================= */

EOF
                    else
                        echo "[INFO] UI patch already exists, skip"
                    fi
                else
                    echo "[WARN] app.js not found, skip UI patch"
                fi
                '''

                archiveArtifacts artifacts: 'test_execution.log', allowEmptyArchive: true
            }
        }
    }
}

