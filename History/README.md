# History

归档目录（**不是**活跃用例）：

- 旧无后缀 / 分后缀 CSV
- 已移出 CI 的 reboot/dc/basic_io/basic_rebuild_io
- lawdisk/filesystem 的 `*_4k` / `*_512` 分拆脚本与 CSV（现已合并为单一用例，靠手动改 CSV）
- mix 的 `Input_Config_mix_*.csv`（mix 已改为仅用 random_choice，不再读 CSV）
- `Input_Config_filesystem.csv`（filesystem 已改为内置轮次模型，不再读 CSV）
- `Input_Config_random_io_*.csv`（random_io 改为 plan_4k/plan_512 生成，不再读 CSV）
- `powercycle_launch.py` 及对应单测

活跃 CI 用例：

`test_ci_00_env_prepare` … `test_ci_06_random_io_512`

- `test_ci_01_lawdisk` / `test_ci_02_filesystem`：不区分 4k/512
- `mix` / `random_io`：仍分 4k / 512

电源循环（reboot/dc）完整能力在 Git 分支 **`PowerCycle`**。
