# RAID_NVME PowerCycle

基于 Pytest + Jenkins 的 **电源循环** 自动化分支：在目标机上跑
`env_prepare` / `reboot` / `dc`。

## 主要能力

- 多节点：Jenkins `TARGET_IPS` 并发调度
- 远程部署：`/root/Cyril/Jenkins/<JOB>/<BRANCH>/build-<N>/`
- reboot/dc 异步触发后，由 `powercycle/wait_powercycle_completion.sh` 闭环多圈
- Allure / JUnit 回收与飞书通知

## 目录

```text
RAID_NVME/
├── Jenkinsfile
├── nvme_raid_test.py
├── test_items.txt
├── IO_Stress/              # powercycle_direct.sh、fio_powercycle、powercycle_random
├── MachineCheck/
├── powercycle/                     # wait_powercycle_completion.sh 等
└── test_items/
    ├── test_powercycle_00_env_prepare.py
    ├── test_powercycle_01_reboot.py
    ├── test_powercycle_02_dc.py
    └── powercycle_launch.py
```

## 配置测试项

编辑 `test_items.txt`：

1. **SELECTION**：`名称 序号`；行首 `#` = 不跑
2. **reboot / dc 必须单独启用**（`validate_powercycle_plan` 禁止与其它用例同跑）
3. 参数块：

| 键 | 含义 |
|---|---|
| `FIO_CYCLES` | 电源循环次数（仅 reboot/dc） |
| `IGNORE_ERROR` | MachineCheck 不一致是否继续 |
| `FIO_DISKS` | 指定数据盘；空=全部数据盘 |

默认启用 `test_powercycle_01_reboot`。Restore 用 Jenkins 参数 `RESTORE`（非测试项）。

## Jenkins

- **Build with Parameters**：`TARGET_IPS`、`RESTORE`、`MANUAL_MR_IID` / `MANUAL_KERNEL_DRIVER_REF`、`TARGET_PASSWORD`
- 密码 SSH：`sshpass`（`powercycle/ensure_sshpass.sh`）
- 选中 reboot/dc 时 Pipeline 会调用 `wait_powercycle_completion.sh`

## 注意

本框架会对远端盘做破坏性操作；确认目标机非生产且可清空。
