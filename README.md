# RAID_NVME / CLI

逐步 CLI 测试分支：用例只做「发什么指令 → 完整回显什么结果」，按测试逻辑串行执行。

## 目录

- `test_items/` — 用例 `test_cli_<NN>_<name>.py`（当前为空，后续自行添加）
- `test_items/cli_step.py` — 单步执行助手：打印命令与完整 stdout/stderr/rc
- `cli/` — Jenkins 远程部署与拉起脚本（精简）
- `nvme_raid_test.py` — 按 `test_items.txt` 选择并串行跑用例

## 选择用例

编辑 `test_items.txt` 的 BEGIN/END SELECTION 块：

```
# test_cli_00_example 0
```

去掉行首 `#` 即启用。

## 飞书 / Allure

构建结束后自动：

1. 收集 Jenkins console + `test_execution_*.log`
2. 生成 Allure（含完整终端日志附件）
3. 推送精简飞书卡片（用户名/密码 +「查看报告」进入 Allure）

可用参数 `DEBUG_NO_FEISHU=true` 跳过推送。

## 本地跑

```bash
python3 nvme_raid_test.py
```
