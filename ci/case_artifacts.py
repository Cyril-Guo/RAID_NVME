"""Recover bounded per-case debug logs without waiting for gcore collection."""
import io
import json
import os
import re
import shutil
import tarfile
from pathlib import Path

MAX_FILES = 256
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
RUN_KEY = re.compile(r"[A-Za-z0-9_]+\Z")


def _warn(path, error):
    print(f"[ARTIFACT_WARNING] {path}: {error}")


def _local_files(directory, boundary):
    if directory.is_symlink() or not directory.is_dir():
        return
    for parent, dirs, files in os.walk(directory, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(parent) / d).is_symlink())
        for name in sorted(files):
            path = Path(parent) / name
            if not path.is_symlink() and path.resolve().is_relative_to(boundary):
                yield path


def _archive_logs(output, boundary, paths):
    """Keep bounded tails and record omissions; never read cores or symlink targets."""
    manifest = [f"scope={boundary.name}", f"max_files={MAX_FILES}",
                f"max_file_bytes={MAX_FILE_BYTES}", f"max_total_bytes={MAX_TOTAL_BYTES}"]
    total = count = 0
    partial = output.with_suffix(output.suffix + ".partial")
    try:
        with tarfile.open(partial, "w:gz", compresslevel=1) as archive:
            for path in paths:
                if count >= MAX_FILES or total >= MAX_TOTAL_BYTES:
                    manifest.append("remaining_files_omitted=archive_limit")
                    break
                if path.is_symlink() or not path.resolve().is_relative_to(boundary):
                    continue
                relative = path.relative_to(boundary).as_posix()
                # Archive existing diagnostics, never memory dumps / binary payloads.
                if path.suffix.lower() in (".gz", ".zip", ".xz", ".core") or path.name.startswith(("core.", "gcore")):
                    continue
                try:
                    with path.open("rb") as handle:
                        size = os.fstat(handle.fileno()).st_size
                        limit = min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - total)
                        handle.seek(max(0, size - limit))
                        data = handle.read(limit)
                    member = tarfile.TarInfo(relative)
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
                    manifest.append(f"{relative}: original_bytes={size} captured_bytes={len(data)} tail_only={size > len(data)}")
                    total += len(data)
                    count += 1
                except OSError as exc:
                    manifest.append(f"{relative}: unavailable={exc}")
            manifest.extend([f"captured_files={count}", f"captured_bytes={total}"])
            data = ("\n".join(manifest) + "\n").encode("utf-8")
            member = tarfile.TarInfo("collection_manifest.txt")
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
        partial.replace(output)
    except OSError as exc:
        _warn(output, exc)
        return False
    print(f"[CASE_LOGS] {output.name}: files={count} captured_bytes={total}")
    return True


def _copy_allure(case_dir, destination, run_key):
    source_dir = case_dir / "allure-results"
    if source_dir.is_symlink() or not source_dir.is_dir():
        return
    for source in source_dir.iterdir():
        if source.is_symlink() or not source.is_file():
            continue
        destination_path = destination / source.name
        try:
            if source.name.endswith("monitor_attachments.json"):
                pending = json.loads(source.read_text(encoding="utf-8"))
                for entry in pending:
                    entry.setdefault("run_key", run_key)
                destination_path = destination / f"{run_key}_{source.name}"
                destination_path.write_text(json.dumps(pending, ensure_ascii=False), encoding="utf-8")
            else:
                replace = not destination_path.exists()
                if source.name.endswith(("-result.json", "-container.json")):
                    json.loads(source.read_text(encoding="utf-8"))
                    if not replace:
                        try:
                            json.loads(destination_path.read_text(encoding="utf-8"))
                        except ValueError:
                            replace = True
                if replace:
                    # Preserve completed root results and their later attachments.
                    shutil.copy2(source, destination_path)
        except (OSError, ValueError) as exc:
            _warn(source, exc)


def copy_case_outputs(case_dir, repo_root, run_key):
    case_dir, repo_root = Path(case_dir).resolve(), Path(repo_root).resolve()
    if not RUN_KEY.fullmatch(run_key) or case_dir == repo_root:
        return
    destination = repo_root / "allure-results"
    destination.mkdir(parents=True, exist_ok=True)
    report = case_dir / f"report_{run_key}.xml"
    if report.is_file() and not report.is_symlink():
        try:
            shutil.copy2(report, repo_root / report.name)
        except OSError as exc:
            _warn(report, exc)
    _copy_allure(case_dir, destination, run_key)

    def paths():
        yield from sorted(case_dir.glob("*.log"))
        yield from _local_files(case_dir / "IO_Stress" / "log", case_dir)
        if not (case_dir / "Stress_Monitor").is_symlink():
            yield from _local_files(case_dir / "Stress_Monitor" / "monitor_log", case_dir)

    source = f"case_debug_{run_key}.tar.gz"
    # A completed case snapshot was taken before gcore; salvage reuses it.
    if (destination / source).is_file() or _archive_logs(destination / source, case_dir, paths()):
        entry = {"item": run_key.split("__", 1)[0], "run_key": run_key,
                 "attachment": {"name": f"用例调试日志 {run_key}（含采集清单）",
                                "source": source, "type": "application/gzip"}}
        (destination / f"case_{run_key}_monitor_attachments.json").write_text(
            json.dumps([entry], ensure_ascii=False), encoding="utf-8")


def recover_case_outputs(repo_root):
    repo_root = Path(repo_root).resolve()
    cases = repo_root / "cases"
    if cases.is_symlink() or not cases.is_dir():
        return
    for case in sorted(cases.iterdir()):
        if case.is_dir() and not case.is_symlink() and RUN_KEY.fullmatch(case.name):
            copy_case_outputs(case, repo_root, case.name)
    # The monitor tree is shared across cases. Do not pretend its final snapshot
    # belongs to every historical case; label it explicitly as node-wide evidence.
    monitor = repo_root / "Stress_Monitor" / "monitor_log"
    if monitor.is_dir() and not monitor.is_symlink():
        destination = repo_root / "allure-results"
        destination.mkdir(exist_ok=True)
        source = "node_monitor_snapshot.tar.gz"
        if _archive_logs(destination / source, repo_root, _local_files(monitor, repo_root)):
            entry = {"scope": "node", "attachment": {"name": "节点监控快照（收尾时，非单用例）",
                     "source": source, "type": "application/gzip"}}
            (destination / "node_monitor_attachments.json").write_text(
                json.dumps([entry], ensure_ascii=False), encoding="utf-8")
