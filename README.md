# RAID_NVME Test Automation Framework

这是一个基于 Pytest 和 Jenkins 的自动化测试框架，用于在多节点服务器上并发执行 RAID 相关的自动化测试。它支持自动远程部署、并发执行、测试报告合并以及飞书（Lark）结果通知功能。

## 🌟 主要功能

- **分布式并发执行**：通过 Jenkins 并发调度，可同时对 `target_ips.txt` 中配置的多个节点进行测试。
- **自动化环境部署**：Jenkins Pipeline 会通过 SSH 自动将测试代码部署到远端服务器（目录 `/tmp/jenkins_nvme_xxx`），并自动加载和安装所需要的 Python 运行依赖。
- **Allure 监控报告合并**：自动从所有远端测试节点中回收测试产物（`.xml` 控制台日志和 `allure-results`），统一生成直观的 Allure UI 评估报告。
- **飞书通知集成**：测试完成后，通过自定义飞书机器人 Webhook，自动实时推送详尽的测试结果与成功/失败数据到飞书群组。

## 📁 目录结构

```text
RAID_NVME/
├── Jenkinsfile            # Jenkins 流水线定义脚本，包含集群并发逻辑与飞书通知
├── nvme_raid_test.py      # 主测试执行调度脚本
├── requirements.txt       # Python 依赖包 (pytest, allure-pytest 等)
├── target_ips.txt         # 存放被测目标服务器的 IP 列表
├── conftest.py            # Pytest 全局配置
└── sub_cases/             # 测试用例目录，将具体的 test_*.py 用例脚本存放在此
```

## 🔑 SSH 免密登录配置 (重要)

为了使 Jenkins 能够顺畅地部署和执行远程测试，必须确保 Jenkins 服务器能够免密登录到所有目标节点。请按照以下步骤操作：

1.  **切换到 Jenkins 用户** (极其重要 ⚠️):
    ```bash
    sudo su -s /bin/bash jenkins
    ```
2.  **生成 SSH 密钥对**:
    ```bash
    ssh-keygen -t rsa -b 4096
    # 一路回车即可，不要设置密码
    ```
3.  **将公钥分发给远端被测机**:
    ```bash
    ssh-copy-id root@<目标IP>
    # 例如: ssh-copy-id root@192.168.1.100
    ```
4.  **测试免密登录是否生效**:
    ```bash
    ssh root@<目标IP>
    # 如果不需要输入密码直接进入，则配置成功
    ```

## 🚀 快速使用说明

### 1. 配置测试目标节点
编辑项目根目录中的 `target_ips.txt`，将所有需要测试的节点 IP 地址逐行填入。

### 2. 在 Jenkins 中触发任务 (带参数预览)
在 Jenkins 界面点击 **"Build with Parameters"**，你可以看到以下可配置项：

- **测试项勾选**: 自由选择运行 `Reboot`, `DC`, `Lawdisk`, `Filesystem`, `Mix` 或 `Specify` 等测试。
- **FIO_CYCLES**: 设置 Powercycle 测试的循环次数 (默认 100)。
- **FIO_DISKS**: 当勾选 `Specify` 测试时，在此输入要测试的磁盘名称 (如 `sdb,sdc`)。
- **ALLOW_DESTRUCTIVE_FIO**: 选择是否开启破坏性写入。

### 3. 查看结果
- **Allure 报告**: 详尽展示每个测试项的执行结果、耗时及日志。
- **错误追踪**: 若测试失败，脚本会自动从远端抓取 `IO_Stress/log/TestErrorLog` 硬件报错日志并关联到报告中。
- **飞书通知**: 任务结束后，飞书群组会收到包含成功率和报告链接的统计卡片。

## ⚠️ 注意事项

* 本框架的测试流中开启了 `ALLOW_DESTRUCTIVE_FIO=1` 可选参数。这可能触发破坏性测试，因此请**务必确保远端测试设备并非生产环境且可以被格式化/清空数据**。
* `Jenkinsfile` 中默认写入了特定的飞书 Webhook 地址与机器人 UI 解析卡片。如果在其他域/新环境中运行，请替换对应的 `FEISHU_WEBHOOK` 值。
