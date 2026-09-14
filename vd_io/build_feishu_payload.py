#!/usr/bin/env python3
"""Minimal Feishu card for VD_IO: credentials + Allure button only."""
import json
import os


def env(name, default=""):
    return os.environ.get(name, default)


def remove_stale_payload(path="feishu_payload.json"):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def load_failure_summary(path="failure_summary.txt", max_length=2200):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            summary = handle.read().strip()
    except OSError:
        return ""
    if len(summary) > max_length:
        return summary[: max_length - 3] + "..."
    return summary


# Terminal hard stops only. Do NOT treat plain "FIO command failed" as hard:
# with MIX_FAIL_ON_ANY=no those lines are recorded while the case continues.
_HARD_SUMMARY_MARKERS = (
    "fio stage failed",
    "fio stage abort",
    "mix_fail_on_any=yes, fail",
    "idle watchdog timeout",
    "idle watchdog fired",
    "test_execution_status=failed",
    "environment_prepare_status=failed",
    "physical_restore_status=failed",
    "insmod ./draid.ko failed",
    "draid kernel module load failed",
    "draid module load failed",
    "traceback",
    "assertionerror",
)


def summary_indicates_hard_failure(summary):
    lowered = (summary or "").lower()
    if "mix_fail_on_any=no, continue" in lowered and "mix_fail_on_any=yes, fail" not in lowered:
        stage_stops = (
            "fio stage failed",
            "fio stage abort",
            "idle watchdog timeout",
            "idle watchdog fired",
            "test_execution_status=failed",
            "environment_prepare_status=failed",
            "physical_restore_status=failed",
            "traceback",
            "assertionerror",
        )
        return any(marker in lowered for marker in stage_stops)
    return any(marker in lowered for marker in _HARD_SUMMARY_MARKERS)


def main():
    total = int(env("TOTAL", "0"))
    report_kind = env("REPORT_KIND", "tests").strip().lower() or "tests"
    failure_summary = load_failure_summary()

    if total <= 0 and not failure_summary:
        remove_stale_payload()
        print("NO_FEISHU_PAYLOAD=empty_metrics")
        return

    if total <= 0 and failure_summary:
        total = 1
        report_kind = "infra"

    failed = int(env("FAILED", "0"))
    errors = int(env("ERRORS", "0"))
    if total == 1 and failed == 0 and errors == 0 and report_kind == "infra":
        errors = 1
    hard_summary = summary_indicates_hard_failure(failure_summary)
    if hard_summary and failed == 0 and errors == 0:
        errors = 1
        if report_kind == "empty":
            report_kind = "infra"
            total = max(total, 1)

    build_result = env("BUILD_RESULT", "SUCCESS").upper()
    if hard_summary and build_result in ("", "SUCCESS"):
        build_result = "FAILURE"
    build_failed = build_result not in ("", "SUCCESS")
    infra_report = report_kind == "infra"
    status_color = (
        "blue"
        if not build_failed and failed + errors == 0 and total > 0 and not infra_report
        else "red"
    )

    job_name = env("JOB_NAME", "SMOKE")
    build_number = env("BUILD_NUMBER", "unknown")
    build_url = env("BUILD_URL", "").rstrip("/") + ("/" if env("BUILD_URL") else "")
    build_label = f"{job_name} #{build_number}"
    title_suffix = " [环境/执行失败]" if infra_report else ""
    allure_url = f"{build_url}allure/" if build_url else "about:blank"

    elements = [
        {
            "tag": "div",
            "fields": [
                {"is_short": True, "text": {"tag": "lark_md", "content": "**用户名:** dapustor"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": "**密码:** Admin@9000"}},
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
    ]

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": f"NVMe_RAID(F6501) {build_label}{title_suffix}",
                },
                "template": status_color,
            },
            "elements": elements,
        },
    }
    with open("feishu_payload.json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)


if __name__ == "__main__":
    main()
