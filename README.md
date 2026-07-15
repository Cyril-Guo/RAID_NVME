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
编辑项目根目录中的 `test_items.txt`。**每个测试项就是一个 `[item]` 块**，开关和参数都在同一个块里，
一处搞定，不用两头看。可用项：`reboot`、`dc`、`lawdisk`、`filesystem`、`mix`。

想跑哪个，就把它块里的 `enable` 改成 `yes`（`no` 即跳过）；参数按需改，不改用默认值。

```text
# 要跑：enable = yes
[lawdisk]
enable          = yes
IGNORE_ERROR    = no
FIO_DISKS       =
STRESS_MONITOR  = yes
MONITOR_RUNTIME = 300

# 不跑：enable = no
[reboot]
enable          = no
FIO_CYCLES      = 10
IGNORE_ERROR    = no
FIO_DISKS       =
STRESS_MONITOR  = no
MONITOR_RUNTIME =
```

参数含义：

- `FIO_CYCLES`：电源循环次数（仅 `reboot`/`dc` 有效；压测项循环由 CSV 与 runtime 决定，不使用此参数）。
- `IGNORE_ERROR`：MachineCheck 结果不一致时是否继续 (yes/no)。
- `FIO_DISKS`：指定数据盘 (如 `sdb,sdc`)，留空为全部数据盘。
- `STRESS_MONITOR` / `MONITOR_RUNTIME`：后台压力监控开关与时长。

> 只有 `enable = yes` 的测试项会执行，并按固定顺序
> （`reboot → dc → lawdisk → filesystem → mix`）运行；
> 各项以自己 `[item]` 块中的参数独立执行，结果统一合并到同一份 Allure / JUnit 报告中。
>
> 停止/清理（restore）不再是测试项，已改由 Jenkins Web 的 `RESTORE` 选项随时触发（见下文）。

> SMOKE 分支的 Jenkins 任务测试项与配置完全由仓库内的 `test_items.txt` 决定，
> 随代码一起部署到被测节点，保证"配置即代码"。Web 界面仅保留一个 `RESTORE`
> 选项用于随时停止测试（见下文）。

### 3. 在 Jenkins 中触发任务
两种触发方式：

**手动触发**：在 Jenkins 界面点击 **"Build with Parameters"**：
- 直接构建（`RESTORE` 不勾选）即按 `test_items.txt` 执行测试。
- 勾选 **`RESTORE`** 后构建：本次不执行测试，仅对 `target_ips.txt` 中所有节点
  **立即停止**正在运行的测试（含后台 FIO / 监控进程），并恢复系统环境
  （还原自动登录、开机自启等配置）。用于随时中止测试。

**自动触发（kernel_driver MR 变化 1 分钟轮询）**：`Jenkinsfile` 每 1 分钟通过
GitLab API 检查 `kernel_driver` 的 Merge Request 列表（包含打开、已合并、已关闭）。
只要任一 MR 的状态、更新时间、头部提交或 merge commit 发生变化，即自动运行冒烟测试。
打开中的 MR 会 checkout source branch，并固定到 MR 当前 `sha`；已合并 MR 会 checkout
target branch，并优先固定到 merge commit。已关闭 MR 会记录该变化但不运行破坏性测试。

RAID_NVME 测试框架自身的 `checkout` 设为 `poll:false`，因此往测试框架推代码**不会**
误触发破坏性测试。没有 MR 变化时，本次构建会标记为 `NOT_BUILT`，不会进入测试和飞书报告流程。

> 需要在 Jenkins 中预先完成一次性配置：
> 1. **添加 SSH 凭据**：Manage Jenkins → Credentials → 新增 *SSH Username with private key*，
>    凭据 ID 填 `kernel_driver_ssh`（与 `Jenkinsfile` 的 `KERNEL_DRIVER_CRED` 一致），
>    私钥需对 `192.168.21.185` 的 `raid_max/kernel_driver` 有读取权限。
> 2. **添加 GitLab API Token 凭据**：Manage Jenkins → Credentials → 新增 *Secret text*，
>    凭据 ID 填 `kernel_driver_gitlab_token`（与 `Jenkinsfile` 的
>    `KERNEL_DRIVER_GITLAB_TOKEN_CRED` 一致）。Token 只需要能读取
>    `raid_max/kernel_driver` 的 Merge Request API。
> 3. **信任 Git 主机指纹**：Manage Jenkins → Security → Git Host Key Verification 配置为
>    “Accept first connection” 或把 `192.168.21.185` 加入 known_hosts，否则首次克隆会因主机校验失败。
> 4. 构建方式确定前，`构建与安装 kernel_driver` 为占位阶段（只打印 TODO，不做实际编译）。
>    后续补充：把 `kernel_driver` 源码部署到各节点 → 编译 → 安装/加载驱动，再跑 FIO 冒烟。

### 4. 查看结果
- **Allure 报告**: 详尽展示每个测试项的执行结果、耗时及日志。
- **错误追踪**: 若测试失败，脚本会自动从远端抓取 `IO_Stress/log/TestErrorLog` 硬件报错日志并关联到报告中。
- **飞书通知**: 任务结束后，飞书群组会收到包含成功率和报告链接的统计卡片。

## ⚠️ 注意事项

* 本框架的测试流中开启了 `ALLOW_DESTRUCTIVE_FIO=1` 可选参数。这可能触发破坏性测试，因此请**务必确保远端测试设备并非生产环境且可以被格式化/清空数据**。
* `Jenkinsfile` 中默认写入了特定的飞书 Webhook 地址与机器人 UI 解析卡片。如果在其他域/新环境中运行，请替换对应的 `FEISHU_WEBHOOK` 值。
