import os
import shlex
import subprocess
import time
from datetime import datetime

import allure
import pytest


def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_text(path):
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _attach_if_exists(path, name):
    text = _read_text(path)
    if text:
        allure.attach(text, name=name, attachment_type=allure.attachment_type.TEXT)
    return text


def trigger_background_fio(io_stress_dir, item, fio_args, wait_seconds=2):
    os.makedirs(os.path.join(io_stress_dir, "log", "ResultLog"), exist_ok=True)
    result_log_dir = os.path.join(io_stress_dir, "log", "ResultLog")
    launch_log = os.path.join(io_stress_dir, "log", "ResultLog", "{}_launch.log".format(item))
    pid_file = os.path.join(io_stress_dir, "log", "ResultLog", "{}_launch.pid".format(item))
    command_log = os.path.join(result_log_dir, "{}_command.log".format(item))
    command = ["bash", "./Fio_All.sh"] + fio_args
    command_text = " ".join(shlex.quote(arg) for arg in command)
    trigger_timeout = int(os.environ.get("POWER_CYCLE_TRIGGER_TIMEOUT", "900"))

    try:
        with open(launch_log, "a", encoding="utf-8") as log_handle:
            log_handle.write("{} [LAUNCH] cwd={}\n".format(ts(), os.path.abspath(io_stress_dir)))
            log_handle.write("{} [LAUNCH] command={}\n".format(ts(), command_text))
        with open(launch_log, "ab") as log_handle, open(os.devnull, "rb") as stdin_handle:
            env = os.environ.copy()
            env["POWER_CYCLE_FORCE_ONCE"] = "1"
            process = subprocess.Popen(
                command,
                cwd=io_stress_dir,
                env=env,
                stdin=stdin_handle,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
    except Exception as exc:
        pytest.fail("Failed to launch background FIO {}: {}".format(item, exc))

    pid = str(process.pid)
    with open(pid_file, "w", encoding="utf-8") as handle:
        handle.write(pid + "\n")

    deadline = time.time() + trigger_timeout
    while time.time() < deadline:
        command_log_text = _read_text(command_log)
        if "request start" in command_log_text:
            _attach_if_exists(launch_log, "{} launch log".format(item))
            allure.attach(command_log_text, name="{} command log".format(item), attachment_type=allure.attachment_type.TEXT)
            print("{} [INFO] Background FIO {} reached power-cycle command, pid={}.".format(ts(), item, pid))
            return

        return_code = process.poll()
        if return_code is not None:
            launch_log_text = _attach_if_exists(launch_log, "{} launch log".format(item))
            pytest.fail(
                "Background FIO {} exited before reaching power-cycle command, rc={}.\n{}"
                .format(item, return_code, launch_log_text[-4000:])
            )

        time.sleep(wait_seconds)

    launch_log_text = _attach_if_exists(launch_log, "{} launch log".format(item))
    command_log_text = _attach_if_exists(command_log, "{} command log".format(item))
    pytest.fail(
        "Background FIO {} did not reach power-cycle command within {} seconds.\n{}\n{}"
        .format(item, trigger_timeout, launch_log_text[-3000:], command_log_text[-1000:])
    )
