"""CLI step helpers: print the exact command, then the full response."""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Mapping, Sequence, Union


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fmt_cmd(cmd: str | Sequence[str]) -> str:
    if isinstance(cmd, str):
        return cmd
    return subprocess.list2cmdline([str(x) for x in cmd])


@dataclass
class StepResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run_step(
    cmd: str | Sequence[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    shell: bool | None = None,
    check: bool = True,
    timeout: float | None = None,
    step_name: str = "",
) -> StepResult:
    """Run one command: echo command, print full output, echo rc.

    check=True raises AssertionError on non-zero rc (pytest-friendly).
    """
    if shell is None:
        shell = isinstance(cmd, str)
    display = _fmt_cmd(cmd)
    title = f" [{step_name}]" if step_name else ""
    print(f"\n=====[{_ts()}] CMD{title}=====", flush=True)
    print(display, flush=True)
    print("----- OUTPUT BEGIN -----", flush=True)

    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd,
            env=dict(env) if env is not None else None,
            shell=shell,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        err = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        if out:
            print(out, end="" if out.endswith("\n") else "\n", flush=True)
        if err:
            print(err, end="" if err.endswith("\n") else "\n", file=sys.stderr, flush=True)
        print("----- OUTPUT END -----", flush=True)
        print(f"=====[{_ts()}] RC=timeout({timeout}) =====\n", flush=True)
        raise

    if completed.stdout:
        print(
            completed.stdout,
            end="" if completed.stdout.endswith("\n") else "\n",
            flush=True,
        )
    if completed.stderr:
        print(
            completed.stderr,
            end="" if completed.stderr.endswith("\n") else "\n",
            file=sys.stderr,
            flush=True,
        )
    print("----- OUTPUT END -----", flush=True)
    print(f"=====[{_ts()}] RC={completed.returncode} =====\n", flush=True)

    result = StepResult(
        command=display,
        returncode=int(completed.returncode),
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )
    if check and not result.ok:
        raise AssertionError(
            f"command failed rc={result.returncode}: {result.command}"
        )
    return result


StepSpec = Union[str, Sequence[str], tuple[str, Union[str, Sequence[str]]]]


def run_steps(
    steps: Iterable[StepSpec],
    *,
    cwd: str | None = None,
    check: bool = True,
) -> list[StepResult]:
    """Run many steps in order.

    Each item is a command, or (step_name, command).
    """
    results: list[StepResult] = []
    for index, item in enumerate(steps, start=1):
        name = f"step{index}"
        cmd: str | Sequence[str]
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str):
            name = item[0] or name
            cmd = item[1]
        else:
            cmd = item  # type: ignore[assignment]
        results.append(run_step(cmd, cwd=cwd, check=check, step_name=name))
    return results
