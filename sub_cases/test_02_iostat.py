import subprocess
import logging
import pytest
import allure

logger = logging.getLogger(__name__)

@allure.epic("存储硬件基准测试")
@allure.feature("系统级 I/O 负载监控 (iostat)")
def test_system_io_status():
    allure.dynamic.title("系统级 I/O 负载取样与分析 (iostat)")
    
    # 配置取样参数：间隔 1 秒，共取样 10 次（总耗时约 10 秒）
    # 您可以根据需要修改这里的值，比如改为 "5" 就是采样 5 秒
    interval = "1"
    count = "10"
    
    iostat_cmd = ["iostat", "-m", "-x", interval, count]

    with allure.step(f"1. 执行 iostat 命令连续取样 (间隔 {interval}s, 共 {count} 次)"):
        try:
            logger.info(f"开始抓取 iostat 数据: {' '.join(iostat_cmd)}")
            # 注意：iostat 通常不需要 sudo，但如果系统有限制可以加上
            # 加上 -x 参数可以获取更详细的扩展统计信息（如 util% 磁盘使用率，await 延迟）
            result = subprocess.run(iostat_cmd, capture_output=True, text=True)
            
            iostat_output = result.stdout
            error_output = result.stderr

            if "command not found" in iostat_output.lower() or "command not found" in error_output.lower():
                pytest.skip("目标机未安装 sysstat，无法执行 iostat 命令。请先通过 apt/yum 安装 sysstat。")

            if result.returncode != 0:
                logger.error(f"iostat 执行异常: {error_output}")
                pytest.fail(f"iostat 命令执行失败，退出码: {result.returncode}")

            # 将抓取到的 10 秒连续完整日志，作为 .txt 附件放入 Allure 报告
            allure.attach(
                iostat_output, 
                name=f"iostat_1s_{count}times_raw.txt", 
                attachment_type=allure.attachment_type.TEXT
            )
            
            logger.info("iostat 数据抓取并存储成功。")

        except Exception as e:
            pytest.fail(f"执行 iostat 监控时发生未知异常: {e}")

    with allure.step("2. 解析取样结果与状态评估"):
        # 取样结束后，我们可以提取最后一次的打印结果，粗略评估当前的磁盘压力
        try:
            # iostat 输出包含了多次快照，我们通过空行分割，取最后一次有效的快照
            snapshots = [s for s in iostat_output.split('\n\n') if 'Device' in s]
            
            if snapshots:
                last_snapshot = snapshots[-1]
                logger.info(f"最后一次 I/O 快照概览:\n{last_snapshot}")
                
                # 把最后一次的快照直接显示在 Allure 的步骤说明中，方便领导/同事直接在网页端查看
                allure.attach(
                    last_snapshot,
                    name="最终 I/O 快照状态 (包含 %util 使用率)",
                    attachment_type=allure.attachment_type.TEXT
                )
            else:
                logger.warning("未能从 iostat 输出中解析到有效的 Device 数据块。")

        except Exception as e:
            logger.warning(f"解析 iostat 数据时出现小问题，但不影响测试继续: {e}")
