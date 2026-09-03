"""Recover only per-case artifacts; cap diagnostic archive size on hung runs."""
import io
import json
import os
import shutil
import tarfile
from pathlib import Path


MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_FILES = 256


def case_files(case):
    command_log = case / "case_command.log"
    if command_log.is_file() and not command_log.is_symlink():
        yield command_log
    for directory in (case / "IO_Stress" / "log", case / "Stress_Monitor" / "log"):
        if not directory.is_dir() or not directory.resolve().is_relative_to(case.resolve()):
            continue
        for parent, dirs, files in os.walk(directory, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not (Path(parent) / d).is_symlink())
            for name in sorted(files):
                path = Path(parent) / name
                if path.is_file() and not path.is_symlink():
                    yield path


def archive_case(case, destination):
    total = 0
    manifest = ["Per-case diagnostics; large files retain their tail. No device data is read."]
    with tarfile.open(destination, "w:gz") as archive:
        for number, path in enumerate(case_files(case)):
            if number >= MAX_FILES or total >= MAX_ARCHIVE_BYTES:
                manifest.append("Collection capped: file count or total byte limit reached.")
                break
            name = path.relative_to(case).as_posix()
            try:
                size = path.stat().st_size
                length = min(size, MAX_FILE_BYTES, MAX_ARCHIVE_BYTES - total)
                with path.open("rb") as handle:
                    handle.seek(max(0, size - length))
                    data = handle.read(length)
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
                total += len(data)
                manifest.append(f"{name}: captured={len(data)} original={size}" + (" (tail only)" if length < size else ""))
            except OSError as exc:
                manifest.append(f"{name}: unavailable: {exc}")
        if not total:
            manifest.append("No readable per-case logs were recovered.")
        data = ("\n".join(manifest) + "\n").encode("utf-8")
        info = tarfile.TarInfo("collection_manifest.txt")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))


def recover_case_artifacts(directory, items):
    root = Path(directory).resolve()
    allure = root / "allure-results"
    allure.mkdir(exist_ok=True)
    pending = []
    for item in items:
        case = root / "cases" / item
        if not case.is_dir() or case.is_symlink():
            continue
        report = case / f"report_{item}.xml"
        if report.is_file():
            shutil.copy2(report, root / report.name)
        source_allure = case / "allure-results"
        if source_allure.is_dir() and not source_allure.is_symlink():
            for source in source_allure.iterdir():
                if not source.is_file() or source.is_symlink():
                    continue
                name = f"{item}_{source.name}" if source.name.endswith("monitor_attachments.json") else source.name
                if not (allure / name).exists():
                    shutil.copy2(source, allure / name)
        archive = allure / f"case_debug_{item}.tar.gz"
        archive_case(case, archive)
        pending.append({"item": item, "attachment": {"name": f"Case debug: {item}",
                        "source": archive.name, "type": "application/gzip"}})
        print(f"[ARTIFACT_RECOVERY] item={item} archive={archive.name}", flush=True)
    # Stress_Monitor is shared through case-workspace symlinks. Label its snapshot
    # as node-level rather than attributing the same data to a particular case.
    if next(case_files(root), None) is not None:
        archive = allure / "case_debug_node_shared.tar.gz"
        archive_case(root, archive)
        pending.append({"item": "", "scope": "node", "attachment": {
            "name": "Shared node logs (IO_Stress / Stress_Monitor snapshot)",
            "source": archive.name, "type": "application/gzip",
        }})
    if pending:
        (allure / "recovered_monitor_attachments.json").write_text(json.dumps(pending), encoding="utf-8")
    return len(pending)
