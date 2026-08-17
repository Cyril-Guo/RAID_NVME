import gzip
import os

_JOB_RUNNING = " is Running.."
_ERROR_MARKERS = (
    "partial disk failure",
    "FIO command failed",
    "FIO stage abort",
    "idle watchdog timeout",
    "all disks failed",
    "at least one disk had IO",
)
_TEXT_PREVIEW_LIMIT = 1024 * 1024


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


def attach_terminal_output(output_text, name="终端完整输出"):
    import allure

    summary = extract_fio_job_summary(output_text)
    if summary:
        allure.attach(
            summary,
            name="FIO 任务摘要",
            attachment_type=allure.attachment_type.TEXT,
        )
    encoded = output_text.encode("utf-8", errors="replace")
    if len(encoded) <= _TEXT_PREVIEW_LIMIT:
        allure.attach(
            output_text,
            name=name,
            attachment_type=allure.attachment_type.TEXT,
        )
        return
    allure.attach(
        gzip.compress(encoded),
        name=f"{name}.log.gz",
        attachment_type="application/gzip",
        extension="gz",
    )


_MACHINECHECK_DETAIL_FILES = (
    ("MachineCheck 差异记录", os.path.join("log", "TestErrorLog", "machine_diff_error.log")),
    ("MachineCheck diff_all", os.path.join("log", "RawLog", "MachineCheckLog", "MessagesRecord", "diff_all.log")),
)


def _read_text_file(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def attach_machinecheck_records(stress_dir, text="", ignore_error=False):
    import allure
    from datetime import datetime

    parts = []
    attached_files = []
    for name, relpath in _MACHINECHECK_DETAIL_FILES:
        content = _read_text_file(os.path.join(stress_dir, relpath))
        if not content:
            continue
        allure.attach(content, name=name, attachment_type=allure.attachment_type.TEXT)
        attached_files.append(name)
        if name == "MachineCheck 差异记录":
            parts.append(content)

    if not parts and text:
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
        if marker_lines:
            parts.append("\n".join(marker_lines))
            allure.attach(
                "\n".join(marker_lines),
                name="MachineCheck 差异记录",
                attachment_type=allure.attachment_type.TEXT,
            )

    if not parts:
        return False

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{ts} [INFO] MachineCheck differences recorded ({', '.join(attached_files) or 'stdout markers'})")
    if ignore_error:
        print(f"{ts} [WARN] IGNORE_ERROR=yes, record MachineCheck without failing")
    else:
        print(f"{ts} [INFO] IGNORE_ERROR=no, MachineCheck differences will fail the case")
    return True
