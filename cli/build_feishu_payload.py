#!/usr/bin/env python3
"""Minimal Feishu card for CLI: credentials + Allure button only."""
from __future__ import annotations

import json
import os
from pathlib import Path


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def remove_stale_payload(path: str = "feishu_payload.json") -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def main() -> None:
    total = int(env("TOTAL", "0"))
    failed = int(env("FAILED", "0"))
    errors = int(env("ERRORS", "0"))
    build_result = env("BUILD_RESULT", "SUCCESS").upper() or "SUCCESS"
    has_console = Path("jenkins_console.log").is_file() and Path("jenkins_console.log").stat().st_size > 0

    if total <= 0 and not has_console and env("TEST_EXECUTION_ATTEMPTED", "") != "true":
        remove_stale_payload()
        print("NO_FEISHU_PAYLOAD=empty_metrics")
        return

    build_failed = build_result not in ("", "SUCCESS") or (failed + errors) > 0
    status_color = "red" if build_failed else "blue"

    job_name = env("JOB_NAME", "CLI")
    build_number = env("BUILD_NUMBER", "unknown")
    build_url = env("BUILD_URL", "").rstrip("/")
    if build_url:
        build_url += "/"
    build_label = f"{job_name} #{build_number}"
    allure_url = f"{build_url}allure/" if build_url else "about:blank"

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
            "elements": [
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
                    ],
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "查看报告"},
                            "url": allure_url,
                            "type": "primary",
                        }
                    ],
                },
            ],
        },
    }
    with open("feishu_payload.json", "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    print(f"Feishu payload ready: allure={allure_url} color={status_color}")


if __name__ == "__main__":
    main()
