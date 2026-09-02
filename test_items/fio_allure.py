import os

_JOB_RUNNING = " is Running.."
_ERROR_MARKERS = (
    "partial disk failure",
    "FIO command failed",
    "FIO stage abort",
    "idle watchdog timeout",
    "all disks failed",
    "any disk IO error fails",
    "at least one disk had IO",
)
TEXT_PREVIEW_LIMIT = 1024 * 1024
LARGE_CONTENT_HINT = "Content is too large, please refer to the attachment."
FIO_COMMAND_LOG_NAME = "FIO 执行日志"
RESULT_SUMMARY_NAME = "测试结果汇总"
MACHINECHECK_ATTACHMENT_NAME = "MachineCheck 差异记录"
FIO_FAILURE_SUMMARY_NAME = "FIO 故障摘要"


def extract_fio_job_summary(text):
    jobs = []
    errors = []
    events = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if _JOB_RUNNING in line:
            jobs.append(line)
        elif any(marker in line for marker in _ERROR_MARKERS):
            errors.append(line)
        elif "[FIO] start " in line or "[FIO] finish " in line:
            events.append(line)
    header = [
        f"job_running_lines={len(jobs)}",
        f"error_lines={len(errors)}",
        f"fio_start_finish_lines={len(events)}",
        "",
        "===== jobs =====",
    ]
    return "\n".join(
        header
        + jobs
        + ["", "===== errors ====="]
        + errors
        + ["", "===== fio start/finish ====="]
        + events
    )


def job_running_count(text):
    return sum(1 for line in text.splitlines() if _JOB_RUNNING in line)


def attach_named_text(content, name):
    import allure

    text = content or ""
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= TEXT_PREVIEW_LIMIT:
        allure.attach(text, name=name, attachment_type=allure.attachment_type.TEXT)
        return
    allure.attach(
        LARGE_CONTENT_HINT,
        name=name,
        attachment_type=allure.attachment_type.TEXT,
    )
    allure.attach(
        text,
        name=f"{name}.log",
        attachment_type=allure.attachment_type.TEXT,
    )


def attach_named_file(path, name):
    import allure

    if not path or not os.path.isfile(path):
        return False
    try:
        allure.attach.file(
            path,
            name=name,
            attachment_type=allure.attachment_type.TEXT,
        )
    except (OSError, RuntimeError):
        return False
    return True


def attach_case_terminal_output(output_text, output_path=None):
    if attach_named_file(output_path, FIO_COMMAND_LOG_NAME):
        return True
    if not (output_text or "").strip():
        return False
    attach_named_text(output_text, FIO_COMMAND_LOG_NAME)
    return True


def attach_case_fio_summary(output_text):
    summary = extract_fio_job_summary(output_text)
    job_count = 0
    for line in summary.splitlines():
        if line.startswith("job_running_lines="):
            job_count = int(line.split("=", 1)[1])
            break
    if job_count <= 0:
        return False
    attach_named_text(summary, "FIO 任务摘要")
    return True


_MACHINECHECK_DETAIL = os.path.join("log", "TestErrorLog", "machine_diff_error.log")


def _read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def attach_machinecheck_records(stress_dir, text="", ignore_error=False):
    from datetime import datetime

    from test_items.command_output import safe_console_print

    detail = _read_text_file(os.path.join(stress_dir, _MACHINECHECK_DETAIL))
    if not detail and text:
        markers = (
            "MachineCheck inconsistencies found",
            "ERROR: MachineCheck",
            "MachineCheck Log Inconsistency",
            "Whitelist field differences",
        )
        marker_lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and any(marker in line for marker in markers)
        ]
        detail = "\n".join(marker_lines)

    if not detail:
        return False

    attach_named_text(detail, MACHINECHECK_ATTACHMENT_NAME)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe_console_print(f"{ts} [INFO] MachineCheck differences recorded")
    if ignore_error:
        safe_console_print(f"{ts} [WARN] IGNORE_ERROR=yes, record MachineCheck without failing")
    else:
        safe_console_print(f"{ts} [INFO] IGNORE_ERROR=no, MachineCheck differences will fail the case")
    return True
