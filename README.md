# RAID_NVME Test Automation Framework

这是一个基于 Pytest 和 Jenkins 的自动化测试框架，用于在多节点服务器上并发执行 RAID 相关的自动化测试。它支持自动远程部署、并发执行、测试报告合并以及飞书（Lark）结果通知功能。

## 🌟 主要功能

- **分布式并发执行**：通过 Jenkins 并发调度，可同时对 `target_ips.txt` 中配置的多个节点进行测试。
- **自动化环境部署**：Jenkins Pipeline 会通过 SSH 自动将测试代码部署到远端服务器，目录按  
  `/root/Cyril/Jenkins/<JOB>/<BRANCH>/build-<N>/` 分层（CI/SMOKE、分支、构建互不混杂）；  
  各用例在 `cases/<item>/` 下隔离运行，并自动加载安装所需 Python 依赖。
- **Allure 监控报告合并**：自动从所有远端测试节点中回收测试产物（`.xml` 控制台日志和 `allure-results`），统一生成直观的 Allure UI 评估报告。
- **飞书通知集成**：测试完成后，通过自定义飞书机器人 Webhook，自动实时推送详尽的测试结果与成功/失败数据到飞书群组。

## 📁 目录结构

```text
RAID_NVME/
├── Jenkinsfile             # Jenkins 流水线定义脚本，包含集群并发逻辑与飞书通知
├── nvme_raid_test.py       # 主测试执行调度脚本（从 test_items.txt 读取测试项）
├── requirements.txt        # Python 依赖包 (pytest, allure-pytest 等)
├── target_ips.txt          # 存放被测目标服务器的 IP 列表
├── test_items.txt          # 测试项白名单 + 各用例独立参数
├── conftest.py             # Pytest 全局配置
├── IO_Stress/              # FIO 压力测试引擎（共用）：Fio_All.sh、lib/ 等
├── MachineCheck/           # 机器信息采集（共用）：盘符 / NVMe PCIe / 链路与 AER
├── Stress_Monitor/         # 后台压力监控工具（共用）
└── test_items/             # 纯测试项：仅存放各 Pytest 测试用例
    └── test_ci_*.py     # 各测试用例（各自独立、自包含）
```

> 说明：`IO_Stress`、`MachineCheck`、`Stress_Monitor` 为多个测试项共用的引擎/工具，
> 统一放在根目录；`test_items/` 只保留纯粹的测试用例脚本，职责更清晰。

## 🔑 SSH 密码登录（当前方式）

Jenkins 通过 **`sshpass` + 密码** 连接被测机，**不再依赖 SSH 免密公钥**。

- 默认用户：`root`（`TARGET_USER`）
- 默认密码：`123456`（`TARGET_PASSWORD`，可在 Jenkins「Build with Parameters」覆盖）
- SSH 选项强制密码认证：`PreferredAuthentications=password`，`PubkeyAuthentication=no`
- Jenkins 节点首次准备时会执行 `ci/ensure_sshpass.sh` 安装 `sshpass`

确认被测机已开启 root 的密码 SSH 登录即可，无需再配置 `ssh-keygen` / `ssh-copy-id`。

## 🚀 快速使用说明

### 1. 配置测试目标节点
编辑项目根目录中的 `target_ips.txt`，将所有需要测试的节点 IP 地址逐行填入。

### 2. 配置要执行的测试项

编辑项目根目录中的 `test_items.txt`：

1. **`BEGIN/END SELECTION` 块**：列出全部已发现用例，格式为 `名称 序号`。  
   - 行首 `#` = 不跑；去掉 `#` = 跑  
   - **按数字升序执行**（与 `test_ci_NN_*.py` 编号对齐更清晰）  
   - 同步会按序号重排、保留启用状态，并给新用例补上 `# <name> <序号>`（也可手动  
     `python nvme_raid_test.py --sync-selection`）
2. **`[用例名]` 参数块**：每个用例自己的参数，只写该用例会用到的键。

```text
# === BEGIN SELECTION（自动同步；名称后数字为执行顺序，# 表示不跑）===
# reboot 1
# dc 2
lawdisk 3
# filesystem 4
mix 5
# === END SELECTION ===

[lawdisk]
IGNORE_ERROR    = no
FIO_DISKS       =
STRESS_MONITOR  = yes
MONITOR_RUNTIME = 1000
```

上面启用项按序号执行：`lawdisk`(3) → `mix`(5)。下方 `[...]` 只是参数，不决定是否执行。

参数含义：

- `FIO_CYCLES`：电源循环次数（仅 `reboot`/`dc` 有效；压测项循环由 CSV 与 runtime 决定，不使用此参数）。
- `IGNORE_ERROR`：MachineCheck 结果不一致时是否继续 (yes/no)。
- `FIO_DISKS`：指定数据盘 (如 `sdb,sdc`)，留空为全部数据盘。
- `STRESS_MONITOR` / `MONITOR_RUNTIME`：后台压力监控开关与时长（`lawdisk` / `filesystem` / `mix`；`reboot` / `dc` 不支持）。

> 白名单为空时不跑任何用例（破坏性测试的安全默认）。停止/清理（restore）
> 不再是测试项，已改由 Jenkins Web 的 `RESTORE` 选项随时触发（见下文）。

> CI 任务的测试项与配置完全由仓库内的 `test_items.txt` 决定，
> 随代码一起部署到被测节点，保证"配置即代码"。Web 界面仅保留一个 `RESTORE`
> 选项用于随时停止测试（见下文）。

### 3. 在 Jenkins 中触发任务

CI 任务**仅支持手动触发**（无定时轮询、无自动 MR 触发）。在 Jenkins 界面点击
**"Build with Parameters"**：

- 直接构建（`RESTORE` 不勾选）：按 `test_items.txt` 执行测试；被测驱动默认 checkout
  `kernel_driver/main`。
- 可选填写 **`MANUAL_MR_IID`**：按指定 GitLab MR 的 source branch 测试，并固定到该 MR 当前 `sha`
  （优先于分支参数）。
- 可选填写 **`MANUAL_KERNEL_DRIVER_REF`**：按指定 `kernel_driver` 分支测试；留空则用 `main`。
- 勾选 **`RESTORE`** 后构建：本次不执行测试，仅对 `target_ips.txt` 中所有节点
  **立即停止**正在运行的测试（含后台 FIO / 监控进程），并恢复系统环境
  （还原自动登录、开机自启等配置）。用于随时中止测试。

RAID_NVME 测试框架自身的 `checkout` 设为 `poll:false`，因此往测试框架推代码**不会**
误触发破坏性测试。

**raid_cli / dpraid**：每次手动测试构建会检查 `general_tools/raid_cli` 的 `hostraid_cli`
分支；有新提交或本地还没有 `dpraid` 时，拉取到 Jenkins 服务器
`$JENKINS_HOME/.raid_nvme/...repo` 并执行 `./build.sh`。真正执行测试时，会把该 `dpraid`
覆盖到测试机 `/usr/bin/dpraid`。飞书报告会展示本次使用的 `raid_cli` commit。

**Python 测试依赖**：测试机优先使用系统软件源安装 `python3-pytest`，避免无 pip 源时卡在
`pip install pytest`。`allure-pytest` 会尽量通过 pip 安装，但不是硬依赖；缺失时用例仍会运行并
生成 JUnit，Jenkins 后置步骤会把 JUnit 转换为 Allure 报告。

**kernel_driver 驱动准备**：触发测试后，Jenkins 会把当前被测的 `kernel_driver` 源码同步到每台
测试机（默认 `main`，或手动指定的 MR / 分支）。每台测试机执行用例前，会进入
`kernel_driver/drivers/draid` 执行 `make`，生成 `draid.ko` 后先通过
`modinfo -F name ./draid.ko` 识别真实模块名，并按真实模块名和 `draid` 候选卸载已有模块，
再执行 `insmod ./draid.ko`。如果模块卸载失败、加载失败或 `draid.ko` 未生成，构建会
直接失败并打印相关模块状态，不继续使用旧驱动测试。编译前会自动安装内核模块编译依赖：Ubuntu/Debian 使用
`build-essential linux-headers-$(uname -r) kmod`，RHEL 系使用 `make gcc kernel-devel kmod`。
`dpraid` 安装、`draid.ko` 编译/卸载/加载、Python 依赖安装的输出会写入
`environment_prepare_<ip>.log`，并在 Allure 报告中作为 `Environment_Prepare_<ip>` 独立结果展示。

> 需要在 Jenkins 中预先完成一次性配置：
> 1. **添加 SSH 凭据**：Manage Jenkins → Credentials → 新增 *SSH Username with private key*，
>    凭据 ID 填 `kernel_driver_ssh`（与 `Jenkinsfile` 的 `KERNEL_DRIVER_CRED` / `RAID_CLI_CRED`
>    一致），私钥需对 `192.168.21.185` 的 `raid_max/kernel_driver` 和
>    `general_tools/raid_cli` 有读取权限。
> 2. **添加 GitLab API Token 凭据**：Manage Jenkins → Credentials → 新增 *Secret text*，
>    凭据 ID 填 `kernel_driver_gitlab_token`（与 `Jenkinsfile` 的
>    `KERNEL_DRIVER_GITLAB_TOKEN_CRED` 一致）。Token 只需要能读取
>    `raid_max/kernel_driver` 的 Merge Request API。
> 3. **信任 Git 主机指纹**：Manage Jenkins → Security → Git Host Key Verification 配置为
>    “Accept first connection” 或把 `192.168.21.185` 加入 known_hosts，否则首次克隆会因主机校验失败。
> 4. 测试机需要能访问对应系统的软件源，用于自动安装内核头文件、`make`、编译器等编译环境。

### 4. 查看结果
- **Allure 报告**: 详尽展示每个测试项的执行结果、耗时及日志。
- **错误追踪**: 若测试失败，脚本会自动从远端抓取 `IO_Stress/log/TestErrorLog` 硬件报错日志并关联到报告中。
- **飞书通知**: 任务结束后，飞书群组会收到包含成功率和报告链接的统计卡片。

## ⚠️ 注意事项

* 本框架会直接对远端测试盘执行破坏性 IO，请**务必确保远端测试设备并非生产环境且可以被格式化/清空数据**。
* `Jenkinsfile` 中默认写入了特定的飞书 Webhook 地址与机器人 UI 解析卡片。如果在其他域/新环境中运行，请替换对应的 `FEISHU_WEBHOOK` 值。
