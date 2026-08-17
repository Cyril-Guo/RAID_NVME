import gzip

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
