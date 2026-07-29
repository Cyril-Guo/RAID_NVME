#!/usr/bin/env python3
import json
import os


def env(name, default=""):
    return os.environ.get(name, default)


def remove_stale_payload(path="feishu_payload.json"):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def load_failure_summary(path="failure_summary.txt", max_length=1800):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            summary = handle.read().strip()
    except OSError:
        return ""
    if len(summary) > max_length:
        return summary[: max_length - 3] + "..."
    return summary


def main():
    total = int(env("TOTAL", "0"))
    if total <= 0:
        remove_stale_payload()
        print("NO_FEISHU_PAYLOAD=empty_metrics")
        return

    failed = int(env("FAILED", "0"))
    errors = int(env("ERRORS", "0"))
    skipped = int(env("SKIPPED", "0"))
    passed = total - failed - errors - skipped
    exec_rate = f"{((total - skipped) / total * 100):.2f}%" if total > 0 else "0%"
    pass_rate = f"{(passed / total * 100):.1f}%" if total > 0 else "0%"
    build_result = env("BUILD_RESULT", "SUCCESS").upper()
    build_failed = build_result not in ("", "SUCCESS")
    status_color = "blue" if not build_failed and failed + errors == 0 and total > 0 else "red"
    font_color = "green" if status_color == "blue" else "red"

    driver_lines = []
    mr_iid = env("KERNEL_DRIVER_MR_IID")
    if mr_iid:
        driver_lines.append(f"MR: !{mr_iid} {env('KERNEL_DRIVER_MR_TITLE')}".strip())
        driver_lines.append(f"Source: {env('KERNEL_DRIVER_REF', 'unknown')}")
        driver_lines.append(f"Updated: {env('KERNEL_DRIVER_MR_UPDATED_AT', 'unknown')}")
    else:
        driver_lines.append(f"Branch: {env('KERNEL_DRIVER_REF', env('KERNEL_DRIVER_BRANCH', 'main'))}")
    driver_lines.append(f"Commit: {env('KERNEL_DRIVER_COMMIT', 'unknown')}")
    driver_lines.append(f"raid_cli({env('RAID_CLI_BRANCH', 'hostraid_cli')}): {env('RAID_CLI_COMMIT', 'unknown')}")

    actions = [{
        "tag": "button",
        "text": {"tag": "plain_text", "content": "查看报告"},
        "url": f"{env('BUILD_URL')}allure/",
        "type": "primary",
    }, {
        "tag": "button",
        "text": {"tag": "plain_text", "content": "实时日志"},
        "url": f"{env('BUILD_URL')}console",
        "type": "default",
    }]
    if env("KERNEL_DRIVER_MR_URL"):
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "查看 MR"},
            "url": env("KERNEL_DRIVER_MR_URL"),
            "type": "default",
        })

    elements = [
        {
            "tag": "div",
            "fields": [
                {"is_short": True, "text": {"tag": "lark_md", "content": "**用户名:** dapustor"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": "**密码:** Admin@9000"}},
                {"is_short": False, "text": {"tag": "lark_md", "content": f"**构建状态:**\n<font color=\"{font_color}\">{build_result or 'UNKNOWN'}</font>"}},
                {"is_short": False, "text": {"tag": "lark_md", "content": f"**触发来源:**\n{env('TRIGGER_SOURCE', 'unknown')}"}},
                {"is_short": False, "text": {"tag": "lark_md", "content": f"**被测驱动:**\n" + "\n".join(driver_lines)}},
                {"is_short": False, "text": {"tag": "lark_md", "content": f"**时间周期:**\n{env('START_STR')} ~ {env('END_STR')}"}},
                {"is_short": False, "text": {"tag": "lark_md", "content": f"**并发节点:**\n{env('IP_LIST')}"}},
            ],
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"通过 **{passed}**  失败 **{failed}**  错误 **{errors}**  Total: **{total}**\n"
                    f"执行率: {exec_rate}   通过率: <font color=\"{font_color}\">{pass_rate}</font>"
                ),
            },
        },
    ]
    failure_summary = load_failure_summary()
    if failure_summary and (build_failed or failed + errors > 0):
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**失败摘要:**\n{failure_summary}",
            },
        })
    elements.append({"tag": "action", "actions": actions})

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "NVMe_RAID(F6501) Test Report"},
                "template": status_color,
            },
            "elements": elements,
        },
    }
    with open("feishu_payload.json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


if __name__ == "__main__":
    main()
