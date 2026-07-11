// 全局变量：存储从 target_ips.txt 读取的 IP 列表
def targetIPs = []
// 全局变量：本次触发对应的 kernel_driver 提交号（用于报告展示）
def kernelDriverCommit = ''
def copyWorkspaceToRemote(ip, remoteDir, targetUser) {
    sh """
    tar \
      --exclude='./.git' \
      --exclude='./kernel_driver' \
      --exclude='./.pytest_cache' \
      --exclude='./__pycache__' \
      --exclude='./allure-results' \
      --exclude='./report.xml' \
      --exclude='./report_*.xml' \
      --exclude='./test_execution_*.log' \
      --exclude='./feishu_payload.json' \
      -czf - . | ssh -o StrictHostKeyChecking=no ${targetUser}@${ip} 'tar -xzf - -C ${remoteDir}'
    """
}

pipeline {
    agent any

    // 鑷姩瑙﹀彂锛氭瘡 15 鍒嗛挓杞 kernel_driver 鐨?main 鍒嗘敮锛屼竴鏃︽湁鏂版彁浜ゅ嵆瑙﹀彂鏈啋鐑熸祴璇曘€?
    // 璇存槑锛氳疆璇粎閽堝 kernel_driver锛堣鍑嗗闃舵 checkout 鐨?poll:true锛夛紱RAID_NVME 娴嬭瘯
    //       妗嗘灦鑷韩鐨?checkout 璁句负 poll:false锛屽洜姝ゅ妗嗘灦鐨勬帹閫佷笉浼氳瑙﹀彂鐮村潖鎬ф祴璇曘€?
    triggers {
        pollSCM('H/15 * * * *')
    }

    // SMOKE 鍒嗘敮锛氭祴璇曢」鍙婂叏灞€閰嶇疆(寰幆娆℃暟/鏄惁蹇界暐閿欒/鎸囧畾纾佺洏/鐩戞帶绛?鍏ㄩ儴鍦?
    // 浠撳簱鏍圭洰褰曠殑 test_items.txt 涓淮鎶わ紝闅忎唬鐮佷竴璧烽儴缃插埌琚祴鑺傜偣銆?
    //
    // 鍞竴淇濈暀鐨勫浘褰㈠寲閫夐」锛歊ESTORE(鍋滄骞舵竻鐞?銆傚嬀閫夊悗鏈鏋勫缓涓嶆墽琛屾祴璇曪紝
    // 浠呭鎵€鏈夌洰鏍囪妭鐐瑰己鍒跺仠姝㈡鍦ㄨ繍琛岀殑娴嬭瘯(鍚悗鍙?FIO / 鐩戞帶杩涚▼)骞舵仮澶嶇郴缁熺幆澧冿紝
    // 鏂逛究闅忔椂涓娴嬭瘯銆?
    parameters {
        booleanParam(
            name: 'RESTORE',
            defaultValue: false,
            description: '浠呭仠姝㈠苟娓呯悊锛氱珛鍗冲仠姝㈡墍鏈夌洰鏍囪妭鐐逛笂姝ｅ湪杩愯鐨勬祴璇?鍚悗鍙?FIO / 鐩戞帶杩涚▼)骞舵仮澶嶇郴缁熺幆澧冿紝鏈鏋勫缓涓嶆墽琛屾祴璇曘€?
        )
    }

    environment {
        // 椋炰功鏈哄櫒浜?Webhook 鍦板潃
        FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/17fe4cfd-5e49-4ceb-b8c4-f002d74340ee'
        // 杩滅▼鐧诲綍鐢ㄦ埛鍚?
        TARGET_USER = 'root' 
        // 瑙ｉ攣鐮村潖鎬у啓鍏ユ祴璇曞紑鍏?(1=鍏佽)
        ALLOW_DESTRUCTIVE_FIO = '1'

        // ===== kernel_driver 婧愮爜浠撳簱锛堣娴嬪璞★級=====
        // main 鍒嗘敮鏈夋柊鎻愪氦鏃惰嚜鍔ㄨЕ鍙戞湰鍐掔儫娴嬭瘯
        KERNEL_DRIVER_REPO   = 'git@192.168.21.185:raid_max/kernel_driver.git'
        KERNEL_DRIVER_BRANCH = 'main'
        // Jenkins 鍑嵁 ID锛氳闂?192.168.21.185 鐨?SSH 绉侀挜锛堥渶鍦?Jenkins 涓鍏堝垱寤猴紝瑙?README锛?
        KERNEL_DRIVER_CRED   = 'kernel_driver_ssh'
    }

    stages {
        stage('鍑嗗闃舵锛氭媺鍙栦唬鐮佷笌璇诲彇 IP') {
            steps {
                cleanWs()

                // RAID_NVME 娴嬭瘯妗嗘灦锛歱oll:false 鈥斺€?涓嶅弬涓庤疆璇紝鍏舵帹閫佷笉浼氳Е鍙戞湰浠诲姟
                checkout scm: scm, poll: false, changelog: true

                // kernel_driver锛歱oll:true 鈥斺€?鍙備笌杞锛宮ain 鍒嗘敮鏈夋彁浜ゅ嵆瑙﹀彂锛涙祬鍏嬮殕鍒板瓙鐩綍
                script {
                    if (!params.RESTORE) {
                        checkout scm: [
                            $class: 'GitSCM',
                            branches: [[name: "*/${env.KERNEL_DRIVER_BRANCH}"]],
                            userRemoteConfigs: [[
                                url: env.KERNEL_DRIVER_REPO,
                                credentialsId: env.KERNEL_DRIVER_CRED
                            ]],
                            extensions: [
                                [$class: 'RelativeTargetDirectory', relativeTargetDir: 'kernel_driver'],
                                [$class: 'CloneOption', shallow: true, depth: 1, noTags: true, timeout: 30]
                            ]
                        ], poll: true, changelog: true

                        kernelDriverCommit = sh(
                            script: "git -C kernel_driver rev-parse --short HEAD 2>/dev/null || echo unknown",
                            returnStdout: true
                        ).trim()
                        echo "琚祴 kernel_driver(${env.KERNEL_DRIVER_BRANCH}) 褰撳墠鎻愪氦: ${kernelDriverCommit}"
                    }
                }

                script {
                    if (fileExists('target_ips.txt')) {
                        def ipContent = readFile('target_ips.txt').trim()
                        targetIPs = ipContent.split('\\r?\\n').findAll { it.trim() != '' && !it.startsWith('#') }
                        
                        if (targetIPs.size() == 0) {
                            error "target_ips.txt 涓湭鍙戠幇鏈夋晥 IP 鍦板潃锛?
                        }
                        echo "鍑嗗瀵逛互涓嬭妭鐐规墽琛屽苟鍙戞祴璇? ${targetIPs}"
                    } else {
                        error "鏍圭洰褰曚笅缂哄皯 target_ips.txt 鏂囦欢锛?
                    }
                }
            }
        }

        stage('鏋勫缓涓庡畨瑁?kernel_driver锛堝崰浣嶏紝寰呰ˉ鍏咃級') {
            when { expression { return !params.RESTORE } }
            steps {
                script {
                    echo "琚祴椹卞姩 kernel_driver 鎻愪氦: ${kernelDriverCommit ?: '鏈煡'}"
                    echo "銆愬崰浣嶃€戞闃舵鐢ㄤ簬鎶婃湰娆℃彁浜ょ殑 kernel_driver 閮ㄧ讲鍒板悇琚祴鑺傜偣骞剁紪璇戙€佸畨瑁?鍔犺浇椹卞姩銆?
                    echo "銆愬崰浣嶃€戞瀯寤烘柟寮忓緟瀹氾紙鍐呮牳妯″潡 .ko / 鏋勫缓鑴氭湰 / 鏁存５鍐呮牳锛夛紝纭畾鍚庡湪姝ゅ疄鐜扮湡姝ｇ殑缂栬瘧瀹夎閫昏緫銆?
                    // TODO(kernel_driver 鏋勫缓涓庡畨瑁?:
                    //   1) 灏?kernel_driver 婧愮爜閮ㄧ讲鍒板悇鑺傜偣锛堝綋鍓嶅凡娴呭厠闅嗗湪宸ヤ綔鍖?kernel_driver/ 鐩綍锛?
                    //   2) 鍦ㄨ妭鐐逛笂缂栬瘧椹卞姩
                    //   3) 瀹夎骞跺姞杞介┍鍔紙insmod/modprobe 鎴?make install锛夛紱澶辫触搴斾腑姝㈠悗缁啋鐑?
                }
            }
        }

        stage('鍋滄涓庢竻鐞嗭細闆嗙兢骞跺彂 Restore') {
            when { expression { return params.RESTORE } }
            steps {
                script {
                    def restoreTasks = [:]

                    for (int i = 0; i < targetIPs.size(); i++) {
                        def ip = targetIPs[i]

                        restoreTasks["Restore_${ip}"] = {
                            stage("Restore on ${ip}") {
                                // 鐙珛涓存椂鐩綍锛屼粎鐢ㄤ簬鏈娓呯悊锛岀粨鏉熷悗鍒犻櫎
                                def remoteDir = "/root/Cyril/Jenkins/jenkins_nvme_restore_${env.BUILD_NUMBER}"

                                echo "[${ip}] 1. 绔嬪嵆寮哄埗鍋滄姝ｅ湪杩愯鐨勬祴璇曡繘绋?鍚悗鍙?..."
                                // 鍏堢洿鎺?pkill锛岀‘淇濆嵆浣块儴缃?鑴氭湰寮傚父涔熻兘绗竴鏃堕棿鍋滀綇娴嬭瘯
                                sh """
                                ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} '
                                    pkill -9 -f nvme_raid_test.py 2>/dev/null || true
                                    pkill -2 -f Stress_Monitor/main.py 2>/dev/null || true
                                    pkill -9 -f run_fio.sh 2>/dev/null || true
                                    pkill -9 -f Fio_All.sh 2>/dev/null || true
                                    pkill -9 fio 2>/dev/null || true
                                ' || true
                                """

                                echo "[${ip}] 2. 閮ㄧ讲娓呯悊鑴氭湰..."
                                sh "ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'"
                                // 鎺掗櫎 kernel_driver 婧愮爜澶х洰褰曪紝閬垮厤鎶婃暣妫靛唴鏍告爲浼犲埌鑺傜偣
                                copyWorkspaceToRemote(ip, remoteDir, env.TARGET_USER)

                                echo "[${ip}] 3. 鎵ц restore 鎭㈠绯荤粺鐜(杩樺師鑷姩鐧诲綍/寮€鏈鸿嚜鍚瓑閰嶇疆)..."
                                sh """
                                ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} '
                                    cd ${remoteDir}/IO_Stress && bash ./Fio_All.sh -i restore || true
                                '
                                """

                                echo "[${ip}] 4. 娓呯悊涓存椂鐩綍..."
                                sh "ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} 'rm -rf ${remoteDir}' || true"

                                echo "[${ip}] 鉁?娴嬭瘯宸插仠姝紝绯荤粺鐜宸叉仮澶嶃€?
                            }
                        }
                    }
                    // 骞跺彂瀵规墍鏈夎妭鐐规墽琛屽仠姝笌娓呯悊
                    parallel restoreTasks
                }
            }
        }

        stage('鎵ц闃舵锛氶泦缇ゅ苟鍙戞祴璇?) {
            when { expression { return !params.RESTORE } }
            steps {
                script {
                    def parallelTasks = [:]
                    
                    for (int i = 0; i < targetIPs.size(); i++) {
                        def ip = targetIPs[i] 
                        
                        parallelTasks["Node_${ip}"] = {
                            stage("Test on ${ip}") {
                                // 姣忔鏋勫缓浣跨敤鐙珛鐨勮繙绋嬪伐浣滅洰褰曪紝閬垮厤澶氭鏋勫缓浜掔浉姹℃煋
                                def remoteDir = "/root/Cyril/Jenkins/jenkins_nvme_${env.BUILD_NUMBER}"
                                
                                echo "[${ip}] 1. 閮ㄧ讲浠ｇ爜..."
                                sh "ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} 'rm -rf ${remoteDir} && mkdir -p ${remoteDir}'"
                                // 鎺掗櫎 kernel_driver 婧愮爜澶х洰褰曪紙鍏堕儴缃?缂栬瘧鐢变笂鏂瑰崰浣嶉樁娈靛悗缁疄鐜帮級
                                copyWorkspaceToRemote(ip, remoteDir, env.TARGET_USER)
                                
                                echo "[${ip}] 2. 瀹夎 Python 渚濊禆..."
                                // 閮ㄥ垎绯荤粺(濡?RHEL 9.x 鏈€灏忓寲瀹夎)鑷甫 python3 浣嗘棤 pip锛?
                                // 鍏堟寜闇€寮曞 pip(ensurepip/鍖呯鐞嗗櫒)锛屽啀鍏煎鏂版棫 pip 瀹夎渚濊禆銆?
                                sh """
                                ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} '
                                    cd ${remoteDir}
                                    python3 -m pip --version >/dev/null 2>&1 || python3 -m ensurepip --default-pip >/dev/null 2>&1 || true
                                    python3 -m pip --version >/dev/null 2>&1 || dnf install -y python3-pip >/dev/null 2>&1 || yum install -y python3-pip >/dev/null 2>&1 || apt-get install -y python3-pip >/dev/null 2>&1 || zypper install -y python3-pip >/dev/null 2>&1 || true
                                    python3 -m pip install -r requirements.txt --break-system-packages || python3 -m pip install -r requirements.txt
                                '
                                """
                                
                                echo "[${ip}] 3. 鑾峰彇纭欢鐜淇℃伅..."
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
                                
                                echo "[${ip}] 4. 杩愯姣嶆祴璇曡剼鏈?(nvme_raid_test.py)..."
                                // 娴嬭瘯椤逛笌鍏ㄥ眬閰嶇疆鍧囨潵鑷粨搴撳唴鐨?test_items.txt锛屾棤闇€鍐嶉€忎紶鍙傛暟
                                def testStatus = sh(
                                    returnStatus: true,
                                    script: """
                                    ssh -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip} \"
                                        cd ${remoteDir} && \
                                        ALLOW_DESTRUCTIVE_FIO=${env.ALLOW_DESTRUCTIVE_FIO} \
                                        sudo -E python3 nvme_raid_test.py
                                    \" 2>&1 | awk '{ print strftime("[%Y-%m-%d %H:%M:%S]"), \$0 }' | tee test_execution_${ip}.log
                                    """
                                )
                                
                                echo "[${ip}] 5. 鍥炰紶娴嬭瘯鏁版嵁..."
                                sh """
                                mkdir -p allure-results
                                scp -o StrictHostKeyChecking=no -r ${env.TARGET_USER}@${ip}:${remoteDir}/allure-results/. ./allure-results/ || true
                                scp -o StrictHostKeyChecking=no ${env.TARGET_USER}@${ip}:${remoteDir}/report.xml ./report_${ip}.xml || true
                                """

                                if (testStatus != 0) {
                                    error "[${ip}] nvme_raid_test.py 鎵ц澶辫触锛岄€€鍑虹爜: ${testStatus}"
                                }
                            }
                        }
                    }
                    // 瑙﹀彂骞跺彂鎵ц鎵€鏈変富鏈虹殑娴嬭瘯浠诲姟
                    parallel parallelTasks
                }
            }
        }

        stage('鍚庢湡澶勭悊锛氭祴璇曠幆澧冨睘鎬у悎骞?) {
            when { expression { return !params.RESTORE } }
            steps {
                sh '''
                # 鍚堝苟鎵€鏈夎妭鐐圭殑灞炴€ф枃浠?
                cat allure-results/environment_*.properties > allure-results/environment.properties 2>/dev/null || true
                rm -f allure-results/environment_*.properties
                '''
            }
        }
    }

    post {
        always {
            script {
                // RESTORE(鍋滄/娓呯悊)妯″紡涓嶄骇鐢熸祴璇曟姤鍛婏紝鐩存帴缁撴潫
                if (params.RESTORE) {
                    echo "馃洃 鍋滄涓庢竻鐞嗕换鍔″凡瀹屾垚锛屾湭鎵ц娴嬭瘯锛岃烦杩囨姤鍛婄敓鎴愪笌閫氱煡銆?
                    return
                }

                sh 'sudo chown -R jenkins:jenkins . || true'

                // 鑱氬悎 JUnit XML 鎶ュ憡
                junit testResults: 'report_*.xml', allowEmptyResults: true

                // 鐢熸垚 Allure 鎶ュ憡锛屽苟灏嗘爣棰樿涓?"TEST REPORT"
                allure(
                    includeProperties: true,
                    jdk: '',
                    reportName: 'TEST REPORT', 
                    results: [[path: 'allure-results']]
                )

                // 褰掓。鍚勮妭鐐圭殑瀹屾暣鎵ц鏃ュ織
                archiveArtifacts artifacts: 'test_execution_*.log', allowEmptyArchive: true

                // ===== 鏁版嵁姹囨€荤粺璁?(Python) =====
                // 浣跨敤涓€娆?Python 鎵ц鑾峰彇鎵€鏈夌粺璁℃暟鎹紝閬垮厤閲嶅鍚姩鐜鍜岃В鏋?
                def metricsOutput = sh(script: """
                    python3 - << 'EOF'
import xml.etree.ElementTree as ET
import glob

stats = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
files = glob.glob('report_*.xml')
for f in files:
    try:
        t = ET.parse(f).getroot()
        for attr in stats.keys():
            val = int(t.attrib.get(attr) or sum(int(s.get(attr, 0)) for s in t.findall('.//testsuite')))
            stats[attr] += val
    except: pass
print(f"{stats['tests']} {stats['failures']} {stats['errors']} {stats['skipped']}")
EOF
                """, returnStdout: true).trim()

                def metrics = metricsOutput.split(' ')
                def total   = metrics[0].toInteger()
                def failed  = metrics[1].toInteger()
                def errors  = metrics[2].toInteger()
                def skipped = metrics[3].toInteger()

                def passed   = total - failed - errors - skipped
                def execRate = total > 0 ? String.format("%.2f%%", ((total - skipped) / (double) total) * 100) : "0%"
                def passRate = total > 0 ? String.format("%.1f%%", (passed / (double) total) * 100) : "0%"

                def startStr = new Date(currentBuild.startTimeInMillis).format("yyyy-MM-dd HH:mm:ss")
                def endStr   = new Date().format("yyyy-MM-dd HH:mm:ss")
                def statusColor = (failed + errors == 0 && total > 0) ? "blue" : "red"

                // ===== 椋炰功閫氱煡鍙戦€?=====
                // 鍙戦€佹椂鎶婇泦缇よ妭鐐?IP 鍔犱笂
                def ipListStr = targetIPs.join(", ")
                def fontColor = statusColor == 'blue' ? 'green' : 'red'
                
                // 灏?payload 鍐欏叆鏈湴鏂囦欢杩涜鍙戦€侊紝閬垮厤 curl 鏃剁粓绔В鏋愬鑷村紩鍙疯閿欒鎴柇
                def payload = """
                {
                  "msg_type": "interactive",
                  "card": {
                    "config": { "wide_screen_mode": true },
                    "header": {
                      "title": { "tag": "plain_text", "content": "馃搳 NVMe_RAID(F6501) Test Report" },
                      "template": "${statusColor}"
                    },
                    "elements": [
                      {
                        "tag": "div",
                        "fields": [
                          { "is_short": true, "text": { "tag": "lark_md", "content": "**鐢ㄦ埛鍚?** dapustor" } },
                          { "is_short": true, "text": { "tag": "lark_md", "content": "**瀵嗙爜:** Admin@9000" } },
                          { "is_short": false, "text": { "tag": "lark_md", "content": "**鏃堕棿鍛ㄦ湡锛?*\\n${startStr} ~ ${endStr}" } },
                          { "is_short": false, "text": { "tag": "lark_md", "content": "**骞跺彂鑺傜偣锛?*\\n${ipListStr}" } },
                          { "is_short": false, "text": { "tag": "lark_md", "content": "**琚祴椹卞姩(kernel_driver)锛?*\\n${kernelDriverCommit ?: '鏈煡'}" } }
                        ]
                      },
                      {
                        "tag": "div",
                        "text": {
                          "tag": "lark_md",
                          "content": "鉁旓笍 **${passed}** 鉂?**${failed}** 鉀?**${errors}** Total: **${total}**\\n鎵ц鐜囷細${execRate}   閫氳繃鐜囷細<font color=\\"${fontColor}\\">${passRate}</font>"
                        }
                      },
                      {
                        "tag": "action",
                        "actions": [
                          {
                            "tag": "button",
                            "text": { "tag": "plain_text", "content": "鏌ョ湅璇︽儏" },
                            "url": "${env.BUILD_URL}allure/",
                            "type": "primary"
                          }
                        ]
                      }
                    ]
                  }
                }
                """
                
                writeFile file: 'feishu_payload.json', text: payload
                sh "curl -s -X POST -H 'Content-Type: application/json' -d @feishu_payload.json ${env.FEISHU_WEBHOOK}"
            }
        }
    }
}
