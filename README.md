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
├── Jenkinsfile             # Jenkins 流水线定义脚本，包含集群并发逻辑与飞书通知
├── nvme_raid_test.py       # 主测试执行调度脚本（从 test_items.txt 读取测试项）
├── requirements.txt        # Python 依赖包 (pytest, allure-pytest 等)
├── target_ips.txt          # 存放被测目标服务器的 IP 列表
├── test_items.txt          # 测试项选择文件：勾选要执行的测试项及全局参数
├── conftest.py             # Pytest 全局配置
├── IO_Stress/              # FIO 压力测试引擎（共用）：Fio_All.sh、lib/ 等
├── MachineCheck/           # 硬件检查工具（共用）：MachineCheck.sh 等
├── Stress_Monitor/         # 后台压力监控工具（共用）
└── test_items/             # 纯测试项：仅存放各 Pytest 测试用例
    └── test_smoke_*.py     # 各测试用例（各自独立、自包含）
```

> 说明：`IO_Stress`、`MachineCheck`、`Stress_Monitor` 为多个测试项共用的引擎/工具，
> 统一放在根目录；`test_items/` 只保留纯粹的测试用例脚本，职责更清晰。

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

### 2. 配置要执行的测试项
编辑项目根目录中的 `test_items.txt`。配置分为**两个区域**，勾选与参数各自独立：

**① 测试项选择区**（文件上半部分）：只放测试项名字，去掉行首 `#` 即启用，加回 `#` 即禁用。
勾选测试项时不必再动参数，非常直观。可用项：`reboot`、`dc`、`lawdisk`、`filesystem`、`mix`、`restore`。

```text
lawdisk
filesystem
mix
# reboot
# dc
# restore
```

**② 参数详情区**（文件下半部分）：每个测试项一个 `[item]` 块，只在这里改参数；
未勾选项的参数会被忽略，各项参数与测试项一一对应，互不影响。

- `FIO_CYCLES`：电源循环次数（仅 `reboot`/`dc` 有效；压测项循环由 CSV 与 runtime 决定，不使用此参数）。
- `IGNORE_ERROR`：MachineCheck 结果不一致时是否继续 (yes/no)。
- `FIO_DISKS`：指定磁盘 (如 `sdb,sdc`)，留空为全部。
- `STRESS_MONITOR` / `MONITOR_RUNTIME`：后台压力监控开关与时长。
- 例外：`restore` 仅涉及 `IGNORE_ERROR`、`FIO_DISKS`（负责停止监控与收尾清理）。

```text
[lawdisk]
IGNORE_ERROR=no
FIO_DISKS=
STRESS_MONITOR=yes
MONITOR_RUNTIME=300
```

> 只有“选择区”勾选的测试项才会执行，并按固定顺序（restore 始终最后收尾）运行；
> 各项以自己 `[item]` 块中的参数独立执行，结果统一合并到同一份 Allure / JUnit 报告中。

> SMOKE 分支的 Jenkins 任务已取消图形化参数，测试项与配置完全由仓库内的
> `test_items.txt` 决定，随代码一起部署到被测节点，保证"配置即代码"。

### 3. 在 Jenkins 中触发任务
在 Jenkins 界面直接点击 **"Build Now"** 即可（无需再选择参数）。

### 4. 查看结果
- **Allure 报告**: 详尽展示每个测试项的执行结果、耗时及日志。
- **错误追踪**: 若测试失败，脚本会自动从远端抓取 `IO_Stress/log/TestErrorLog` 硬件报错日志并关联到报告中。
- **飞书通知**: 任务结束后，飞书群组会收到包含成功率和报告链接的统计卡片。

## ⚠️ 注意事项

* 本框架的测试流中开启了 `ALLOW_DESTRUCTIVE_FIO=1` 可选参数。这可能触发破坏性测试，因此请**务必确保远端测试设备并非生产环境且可以被格式化/清空数据**。
* `Jenkinsfile` 中默认写入了特定的飞书 Webhook 地址与机器人 UI 解析卡片。如果在其他域/新环境中运行，请替换对应的 `FEISHU_WEBHOOK` 值。
