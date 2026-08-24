# RAID_NVME Test Automation Framework

这是一个基于 Pytest 和 Jenkins 的自动化测试框架，用于在多节点服务器上并发执行 RAID 相关的自动化测试。它支持自动远程部署、并发执行、测试报告合并以及飞书（Lark）结果通知功能。

## 🌟 主要功能

- **分布式并发执行**：通过 Jenkins 并发调度，可同时对 `target_ips.txt` 中配置的多个节点进行测试。
- **自动化环境部署**：Jenkins Pipeline 通过 **SSH 密码登录**（`sshpass`）将测试代码部署到远端服务器，目录为 `/root/Cyril/Jenkins/<JOB>/<BRANCH>/build-<N>/` 分层（CI/SMOKE、分支、构建互不混杂）；各用例在 `cases/<item>/` 下隔离运行，并自动安装所需 Python 运行依赖、编译/加载 `draid` 驱动。
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

## 🔑 目标机 SSH 密码登录 (重要)

Pipeline **不再依赖** Jenkins → 被测机的 SSH 免密（公钥）。所有连物理机 / QEMU 客户机的 `ssh`/`scp`
都通过 `sshpass` 走密码，并强制 `PreferredAuthentications=password`、`PubkeyAuthentication=no`。

| 对象 | 用户 | 密码来源 | 默认值 |
|------|------|----------|--------|
| 物理机（`target_ips.txt`） | `root`（`TARGET_USER`） | 构建参数 / 环境变量 `TARGET_PASSWORD` | `123456` |
| QEMU 客户机（端口 `2233`） | `root` | `QEMU_VM_PASSWORD`（Jenkinsfile 环境变量） | `1` |

**被测物理机侧只需保证：**

1. `root` 允许密码 SSH 登录（`PasswordAuthentication yes`，且 `PermitRootLogin` 允许）。
2. `root` 密码与流水线一致：默认 **`123456`**；若机器密码不同，在 Jenkins
   **Build with Parameters** 里改 `TARGET_PASSWORD`（自动触发用参数默认值 `123456`）。
3. Jenkins 节点已安装 `sshpass`（流水线会调用 `ci/ensure_sshpass.sh` 尝试自动安装）。

在 Jenkins 节点上可自检物理机密码登录：

```bash
SSHPASS='123456' sshpass -e ssh \
  -o StrictHostKeyChecking=no \
  -o PreferredAuthentications=password \
  -o PubkeyAuthentication=no \
  root@<目标IP> 'echo ok'
```

> 说明：拉取 `kernel_driver` / `raid_cli` 仍使用 Jenkins 凭据 `kernel_driver_ssh`（连 Git 主机
> `192.168.21.185`），与被测机登录无关，二者不要混淆。

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
> 随代码一起部署到被测节点，保证"配置即代码"。Web 参数主要保留 `RESTORE`、`TARGET_PASSWORD`
> 以及调试用选项（见下文）。

### 3. 在 Jenkins 中触发任务
两种触发方式：

**手动触发**：在 Jenkins 界面点击 **"Build with Parameters"**：
- 直接构建（`RESTORE` 不勾选）即按 `test_items.txt` 执行测试，不受 MR 轮询去重限制；
  被测驱动默认 checkout `kernel_driver/main`。
- **`TARGET_PASSWORD`**：物理机 `root` SSH 密码，默认 `123456`；仅当目标机密码不是默认值时再改。
- 勾选 **`SIMULATE_AUTO_MR_TRIGGER`（虚拟机路径）**：先在 **QEMU 虚拟机**里按 `test_items.txt`
  **串行跑完全部勾选用例**，再 **只 poweroff 一次** 归还 NVMe，然后在 **物理机**上对同一批用例再串行跑一遍
  （自动 MR 触发同样是这条路径；避免每个用例来回开关虚拟机）。
- 勾选 **`RESTORE`** 后构建：本次不执行测试，仅对 `target_ips.txt` 中所有节点
  **立即停止**正在运行的测试（含后台 FIO / 监控进程），并恢复系统环境
  （还原自动登录、开机自启等配置）。用于随时中止测试。

**自动触发（kernel_driver 打开中 MR 变化 1 分钟轮询）**：`Jenkinsfile` 每 1 分钟通过
GitLab API 检查 `kernel_driver` 的打开中 Merge Request。标题以 `[WIP]` 开头的 MR
会被过滤，不自动触发测试。只要未过滤的打开中 MR 有新增、更新时间变化或头部提交变化，
即自动运行冒烟测试。测试会 checkout source branch，并固定到 MR 当前 `sha`。

RAID_NVME 测试框架自身的 `checkout` 设为 `poll:false`，因此往测试框架推代码**不会**
误触发破坏性测试。没有打开中的 MR 变化时，本次构建会标记为 `NOT_BUILT`，不会进入测试和飞书报告流程。
如果一个 MR 在两次轮询之间完成创建并合并或关闭，Jenkins 查询打开中 MR 时可能看不到它；
只要 MR 保持打开状态超过一次 1 分钟轮询窗口，就能被监控到并触发。

**环境代码拉取（raid_cli 30 分钟轮询）**：同一个 Jenkins 任务会每 30 分钟检查一次
`general_tools/raid_cli` 的 `hostraid_cli` 分支。发现新提交时，只把代码拉取并保存到 Jenkins
服务器的 `$JENKINS_HOME/.raid_nvme/...repo` 持久目录，然后在该目录执行 `./build.sh`。
编译成功后会校验生成的 `dpraid` 可执行文件；只有校验通过才会记录本次 `raid_cli` 提交。
如果 Jenkins 服务器上还没有初始的 `raid_cli` 仓库或 `dpraid` 可执行文件，会忽略 30 分钟间隔，
先立即拉取并编译一份初始版本。
`raid_cli` 的变化不会触发冒烟测试，也不会进入飞书测试报告流程；只有 `kernel_driver` 的未过滤
打开中 MR 变化才会自动跑测试。真正执行测试时，Jenkins 会在每台测试机开始测试前把这个
`dpraid` 覆盖到 `/usr/bin/dpraid`，保证测试使用最新已编译的工具。测试完成后的飞书报告会
同时展示本次使用的 `raid_cli` commit。

**Python 测试依赖**：测试机优先使用系统软件源安装 `python3-pytest`，避免无 pip 源时卡在
`pip install pytest`。`allure-pytest` 会尽量通过 pip 安装，但不是硬依赖；缺失时用例仍会运行并
生成 JUnit，Jenkins 后置步骤会把 JUnit 转换为 Allure 报告。

**kernel_driver 驱动准备**：触发测试后，Jenkins 会把当前被测的 `kernel_driver` 源码同步到每台
测试机。手动构建使用 `main` 分支；MR 自动触发使用 MR source branch，并固定到 MR 当前 `sha`。
每台测试机执行用例前，会进入 `kernel_driver/drivers/draid` 执行 `make`，生成 `draid.ko` 后先
通过 `modinfo -F name ./draid.ko` 识别真实模块名，并按真实模块名和 `draid` 候选卸载已有模块，
再执行 `insmod ./draid.ko`。如果模块卸载失败、加载失败或 `draid.ko` 未生成，构建会
直接失败并打印相关模块状态，不继续使用旧驱动测试。编译前会自动安装内核模块编译依赖：Ubuntu/Debian 使用
`build-essential linux-headers-$(uname -r) kmod`，RHEL 系使用 `make gcc kernel-devel kmod`。
`dpraid` 安装、`draid.ko` 编译/卸载/加载、Python 依赖安装的输出会写入
`environment_prepare_<ip>.log`，并在 Allure 报告中作为 `Environment_Prepare_<ip>` 独立结果展示。

> 需要在 Jenkins 中预先完成一次性配置：
> 1. **添加 Git SSH 凭据（仅用于拉代码，不是连被测机）**：Manage Jenkins → Credentials →
>    新增 *SSH Username with private key*，凭据 ID 填 `kernel_driver_ssh`
>    （与 `Jenkinsfile` 的 `KERNEL_DRIVER_CRED` / `RAID_CLI_CRED` 一致），私钥需对
>    `192.168.21.185` 的 `raid_max/kernel_driver` 和 `general_tools/raid_cli` 有读取权限。
> 2. **添加 GitLab API Token 凭据**：Manage Jenkins → Credentials → 新增 *Secret text*，
>    凭据 ID 填 `kernel_driver_gitlab_token`（与 `Jenkinsfile` 的
>    `KERNEL_DRIVER_GITLAB_TOKEN_CRED` 一致）。Token 只需要能读取
>    `raid_max/kernel_driver` 的 Merge Request API。
> 3. **信任 Git 主机指纹**：Manage Jenkins → Security → Git Host Key Verification 配置为
>    “Accept first connection” 或把 `192.168.21.185` 加入 known_hosts，否则首次克隆会因主机校验失败。
> 4. **被测机 root 密码**：与 `TARGET_PASSWORD` 一致（默认 `123456`）；Jenkins 节点需可用 `sshpass`
>    （流水线会尝试自动安装）。
> 5. 测试机需要能访问对应系统的软件源，用于自动安装内核头文件、`make`、编译器等编译环境。

### 4. 查看结果
- **Allure 报告**: 详尽展示每个测试项的执行结果、耗时及日志。
- **错误追踪**: 若测试失败，脚本会自动从远端抓取 `IO_Stress/log/TestErrorLog` 硬件报错日志并关联到报告中。
- **飞书通知**: 任务结束后，飞书群组会收到包含成功率和报告链接的统计卡片。

## ⚠️ 注意事项

* 本框架的测试流中开启了 `ALLOW_DESTRUCTIVE_FIO=1` 可选参数。这可能触发破坏性测试，因此请**务必确保远端测试设备并非生产环境且可以被格式化/清空数据**。
* 飞书 Webhook 使用 Jenkins 凭据 `feishu-webhook`（`FEISHU_WEBHOOK`），不要在仓库里硬编码。
* 自动触发构建使用参数默认值：物理机密码即 `TARGET_PASSWORD=123456`；若某台机器密码不同，需改机器密码或仅用手动参数覆盖（自动任务不会记住上次手动输入的密码）。
* 目标机 SSH 必须走密码；仓库内回归测试会拦截对目标机的裸 `ssh`/`scp`（未包 `sshpass`）写法。
