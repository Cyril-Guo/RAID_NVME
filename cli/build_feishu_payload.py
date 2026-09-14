#!/usr/bin/env python3
"""Build Feishu interactive card for CLI branch: results + full terminal log."""
from __future__ import annotations

import json
import os
from pathlib import Path


# Feishu interactive card payload soft limit; keep headroom under ~30KB.
MAX_LOG_CHARS = int(os.environ.get("FEISHU_LOG_MAX_CHARS", "12000"))


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def remove_stale_payload(path: str = "feishu_payload.json") -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def load_console_log(path: str = "jenkins_console.log") -> str:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def clip_log(text: str, limit: int = MAX_LOG_CHARS) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    head = text[: limit - 80].rstrip()
    return (
        head + "\n\n...[log truncated for Feishu size limit; see Jenkins full console / jenkins_console.log]...",
        True,
    )


def main() -> None:
    total = int(env("TOTAL", "0"))
    failed = int(env("FAILED", "0"))
    errors = int(env("ERRORS", "0"))
    skipped = int(env("SKIPPED", "0"))
    build_result = env("BUILD_RESULT", "SUCCESS").upper() or "SUCCESS"
    console = load_console_log()

    # Always notify when there is console/log or countable results.
    if total <= 0 and not console:
        remove_stale_payload()
        print("NO_FEISHU_PAYLOAD=empty_metrics")
        return

    if total <= 0 and console:
        # No junit cases selected, but build still produced logs.
        total = 0

    passed = max(0, total - failed - errors - skipped)
    build_failed = build_result not in ("", "SUCCESS") or (failed + errors) > 0
    status_color = "red" if build_failed else "blue"
    font_color = "red" if build_failed else "green"

    job_name = env("JOB_NAME", "CLI")
    build_number = env("BUILD_NUMBER", "unknown")
    build_url = env("BUILD_URL", "").rstrip("/")
    if build_url:
        build_url += "/"
    build_label = f"{job_name} #{build_number}"

    if total > 0:
        exec_den = max(total - skipped, 0)
        exec_rate = f"{(exec_den / total * 100):.2f}%" if total else "0%"
        pass_rate = f"{(passed / total * 100):.1f}%" if total else "0%"
        stats_text = (
            f"通过 **{passed}**  失败 **{failed}**  错误 **{errors}**  跳过 **{skipped}**  Total: **{total}**\n"
            f"执行率: {exec_rate}   通过率: <font color=\"{font_color}\">{pass_rate}</font>"
        )
    else:
        stats_text = "本次未选择用例（或无 junit），以下为完整终端/执行日志。"

    clipped, truncated = clip_log(console) if console else ("(no console log collected)", False)
    # Feishu lark_md: escape triple backticks lightly by using indented code-ish block
    log_block = clipped.replace("```", "'''")
    log_md = f"**完整测试日志（终端输出）**{'（已截断）' if truncated else ''}:\n```\n{log_block}\n```"

    actions = []
    if build_url:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "Jenkins 构建"},
                "url": build_url,
                "type": "primary",
            }
        )
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "Console Output"},
                "url": f"{build_url}console",
                "type": "default",
            }
        )

    elements = [
        {
            "tag": "div",
            "fields": [
                {
                    "is_short": True,
                    "text": {"tag": "lark_md", "content": "**用户名:** dapustor"},
                },
                {
                    "is_short": True,
                    "text": {"tag": "lark_md", "content": "**密码:** Admin@9000"},
                },
                {
                    "is_short": False,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**构建链接:**\n{build_url or 'unknown'}",
                    },
                },
                {
                    "is_short": False,
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"**构建状态:**\n<font color=\"{font_color}\">"
                            f"{build_result or 'UNKNOWN'}</font>"
                        ),
                    },
                },
                {
                    "is_short": False,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**时间周期:**\n{env('START_STR')} ~ {env('END_STR')}",
                    },
                },
                {
                    "is_short": False,
                    "text": {
                        "tag": "lark_md",
                        "content": f"**并发节点:**\n{env('IP_LIST') or 'unknown'}",
                    },
                },
            ],
        },
        {"tag": "div", "text": {"tag": "lark_md", "content": stats_text}},
        {"tag": "div", "text": {"tag": "lark_md", "content": log_md}},
    ]
    if actions:
        elements.append({"tag": "action", "actions": actions})

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"NVMe_RAID CLI {build_label}",
                },
                "template": status_color,
            },
            "elements": elements,
        },
    }
    with open("feishu_payload.json", "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    print(
        f"Feishu payload ready: total={total} failed={failed} errors={errors} "
        f"log_chars={len(console)} truncated={truncated}"
    )


if __name__ == "__main__":
    main()
