#!/usr/bin/env python3
import json
import os
from urllib.parse import quote


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


def kernel_driver_web_base():
    configured = env("KERNEL_DRIVER_WEB_URL").rstrip("/")
    if configured:
        return configured
    api = env("KERNEL_DRIVER_GITLAB_API", "http://192.168.21.185:8081/api/v4").rstrip("/")
    if api.endswith("/api/v4"):
        return f"{api[: -len('/api/v4')]}/raid_max/kernel_driver"
    return "http://192.168.21.185:8081/raid_max/kernel_driver"


def kernel_driver_code_url():
    """Prefer MR page; otherwise open the tested branch/commit in GitLab."""
    mr_url = env("KERNEL_DRIVER_MR_URL").strip()
    if mr_url:
        return mr_url

    base = kernel_driver_web_base()
    commit = env("KERNEL_DRIVER_COMMIT", "").strip()
    if commit and commit.lower() != "unknown":
        return f"{base}/-/commit/{commit}"

    ref = (
        env("KERNEL_DRIVER_REF")
        or env("KERNEL_DRIVER_BRANCH")
        or "main"
    ).strip()
    return f"{base}/-/tree/{quote(ref, safe='/_-.')}"


def main():
    total = int(env("TOTAL", "0"))
    report_kind = env("REPORT_KIND", "tests").strip().lower() or "tests"
    failure_summary = load_failure_summary()

    if total <= 0 and not failure_summary:
        remove_stale_payload()
        print("NO_FEISHU_PAYLOAD=empty_metrics")
        return

    # Infra-only failures may still notify when summary exists even if counters are empty.
    if total <= 0 and failure_summary:
        total = 1
        report_kind = "infra"

    failed = int(env("FAILED", "0"))
    errors = int(env("ERRORS", "0"))
    skipped = int(env("SKIPPED", "0"))
    if total == 1 and failed == 0 and errors == 0 and report_kind == "infra":
        errors = 1
    passed = max(0, total - failed - errors - skipped)
    exec_rate = f"{((total - skipped) / total * 100):.2f}%" if total > 0 else "0%"
    pass_rate = f"{(passed / total * 100):.1f}%" if total > 0 else "0%"
    build_result = env("BUILD_RESULT", "SUCCESS").upper()
    build_failed = build_result not in ("", "SUCCESS")
    infra_report = report_kind == "infra"
    status_color = "blue" if not build_failed and failed + errors == 0 and total > 0 and not infra_report else "red"
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

    job_name = env("JOB_NAME", "SMOKE")
    build_number = env("BUILD_NUMBER", "unknown")
    build_url = env("BUILD_URL", "").rstrip("/") + ("/" if env("BUILD_URL") else "")
    build_label = f"{job_name} #{build_number}"
    title_suffix = " [环境/执行失败]" if infra_report else ""
    code_url = kernel_driver_code_url()

    actions = [{
        "tag": "button",
        "text": {"tag": "plain_text", "content": "查看报告"},
        "url": f"{build_url}allure/" if build_url else "about:blank",
        "type": "primary",
    }]
    if code_url:
        actions.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "查看MR"},
            "url": code_url,
            "type": "default",
        })

    # Keep pass/fail stats (including env/execution items). Detail logs stay in Allure.
    stats_text = (
        f"通过 **{passed}**  失败 **{failed}**  错误 **{errors}**  Total: **{total}**\n"
        f"执行率: {exec_rate}   通过率: <font color=\"{font_color}\">{pass_rate}</font>"
    )

    elements = [
        {
            "tag": "div",
            "fields": [
                {"is_short": True, "text": {"tag": "lark_md", "content": "**用户名:** dapustor"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": "**密码:** Admin@9000"}},
                {"is_short": False, "text": {"tag": "lark_md", "content": f"**Jenkins构建:**\n{build_label}"}},
                {"is_short": False, "text": {"tag": "lark_md", "content": f"**构建链接:**\n{build_url or 'unknown'}"}},
                {"is_short": False, "text": {"tag": "lark_md", "content": f"**构建状态:**\n<font color=\"{font_color}\">{build_result or 'UNKNOWN'}</font>"}},
                {"is_short": False, "text": {"tag": "lark_md", "content": f"**触发来源:**\n{env('TRIGGER_SOURCE', 'unknown')}"}},
                {"is_short": False, "text": {"tag": "lark_md", "content": f"**被测驱动:**\n" + "\n".join(driver_lines)}},
                {"is_short": False, "text": {"tag": "lark_md", "content": f"**时间周期:**\n{env('START_STR')} ~ {env('END_STR')}"}},
                {"is_short": False, "text": {"tag": "lark_md", "content": f"**并发节点:**\n{env('IP_LIST')}"}},
            ],
        },
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": stats_text},
        },
        {"tag": "action", "actions": actions},
    ]

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"NVMe_RAID(F6501) {build_label}{title_suffix}"},
                "template": status_color,
            },
            "elements": elements,
        },
    }
    with open("feishu_payload.json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


if __name__ == "__main__":
    main()
