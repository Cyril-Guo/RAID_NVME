# CI Allure 日志布局

用例只展示三个同级项目：

- 终端输出：完整 Jenkins Console；缺失时显示 Console 采集说明。
- 测试结果：用例状态、报错、FIO 故障摘要及原始步骤明细。
- 日志收集：该节点、该 run_key 的 FIO 日志、监控日志和已回收故障包。

不再展示 `pytest` 重复分组和 `unknown` 成功占位记录。真实框架异常归入
“测试日志 / 执行诊断”，不会为了清理界面而删除。测试仍使用 pytest 执行。
Set up / Tear down 对应的 fixture 仍正常运行；发布前迁移其附件、保留真实
异常，再清空 Allure 容器的 befores / afters 展示内容。

## 日志回收

正常用例结束后，在 gcore 采集前创建 `case_debug_<run_key>.tar.gz`。收尾或
watchdog 打断后，`salvage_junit_reports.py` 会补回 `cases/<run_key>/` 下的
JUnit、Allure 和轻量调试日志；已有用例快照会复用，不再次压缩。

快照包含用例根目录的 `.log`、`IO_Stress/log/` 和用例独立监控目录。
单文件最多取末尾 4 MiB，总计最多 32 MiB、256 个文件；包内
`collection_manifest.txt` 明确记录原大小、截断、遗漏和实际采集数量。
该快照不替代完整 Jenkins Console、原始日志或 gcore 故障包。

共享监控目录的收尾快照明确标为“节点监控快照（收尾时，非单用例）”，
不能当作每个历史用例的独立监控记录。附件及待关联索引均按节点命名，
再按准确 run_key 关联，避免多节点/重复运行的同名文件覆盖。

控制端已下载的故障包也会加入 Allure；`remote_runner` 包用节点执行日志中
最后一个活动或失败的 ITEM_START / ITEM_END 定位。无法定位时标为节点级
证据，不臆测具体用例。未下载的附件只展示缺失说明，不生成无效下载链接。

修改影响下一次使用本代码的构建。旧报告需要保留原始结果和日志后重新
组装、发布；未实际采回的日志无法靠修改页面恢复。手动 abort 的飞书
通知策略保持不变。
