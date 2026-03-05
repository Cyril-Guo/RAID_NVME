# RAID_NVME Test Automation Framework

这是一个基于 Pytest 和 Jenkins 的自动化测试框架，用于在多节点服务器上并发执行 NVMe 和 RAID 相关的自动化测试。它支持自动远程部署、并发执行、测试报告合并以及飞书（Lark）结果通知功能。

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

## 🚀 快速使用说明

### 1. 配置测试目标节点
编辑项目根目录中的 `target_ips.txt`，将所有需要测试的节点 IP 地址逐行填入：
```text
192.168.1.100
192.168.1.101
```

### 2. 增加测试脚本
在 `sub_cases/` 目录下编写具体的 Pytest 测试脚本（以 `test_` 开头命名），例如 `test_raid_creation.py`。框架的 `nvme_raid_test.py` 会自动探测并调用该目录下的用例。

### 3. 环境准备
Jenkins Pipeline 默认以 `root` 用户远程执行被测节点上的命令。请确保 Jenkins 机器能够免密 SSH 登录到目标 IP，同时远端服务器具备 `python3` 和 `pip` 环境。

### 4. 触发测试任务
在 Jenkins 中触发该项目流水线（Pipeline），执行步骤如下：
1. **获取信息**：Jenkins 读取并解析节点 IP。
2. **下发与执行**：自动向目标机发送代码库，安装 `pytest` 和 `allure-pytest`，随后允许以 Destructive FIO（默认 `ALLOW_DESTRUCTIVE_FIO='1'`）并发触发母脚本 `nvme_raid_test.py`。
3. **搜集报告**：将生成的所有报告文件传输回 Jenkins 归档。
4. **消息通知**：计算整体成功率并将数据卡片推送至飞书。

## ⚠️ 注意事项

* 本框架的测试流中开启了 `ALLOW_DESTRUCTIVE_FIO=1` 可选参数。这可能触发破坏性测试，因此请**务必确保远端测试设备并非生产环境且可以被格式化/清空数据**。
* `Jenkinsfile` 中默认写入了特定的飞书 Webhook 地址与机器人 UI 解析卡片。如果在其他域/新环境中运行，请替换对应的 `FEISHU_WEBHOOK` 值。
