from pathlib import Path

import pytest

import nvme_raid_test
from nvme_raid_test import parse_items_file


def test_repository_test_items_file_is_valid():
    config = Path(__file__).resolve().parents[1] / "test_items.txt"

    selected, params = parse_items_file(config)

    assert selected
    assert "mix" in params
    assert "basic_io" in params
    assert "basic_rebuild_io" in params
    assert "multi_raid_io" in params
    assert "multi_raid_degraded_io" in params


def test_basic_io_items_are_registered_after_existing_smoke_items():
    keys = list(nvme_raid_test.TEST_ITEMS)

    assert keys[-4:] == ["basic_io", "basic_rebuild_io", "multi_raid_io", "multi_raid_degraded_io"]
    assert nvme_raid_test.TEST_ITEMS["basic_io"] == "test_items/test_smoke_06_basic_io.py"
    assert nvme_raid_test.TEST_ITEMS["basic_rebuild_io"] == "test_items/test_smoke_07_basic_rebuild_io.py"
    assert nvme_raid_test.TEST_ITEMS["multi_raid_io"] == "test_items/test_smoke_08_multi_raid_io.py"
    assert nvme_raid_test.TEST_ITEMS["multi_raid_degraded_io"] == "test_items/test_smoke_09_multi_raid_degraded_io.py"


def test_main_prints_item_boundaries():
    source = Path("nvme_raid_test.py").read_text(encoding="utf-8")

    assert "[ITEM_START] {item}" in source
    assert "[ITEM_END] {item} exit_code={exit_code}" in source


def test_parse_selection_block_controls_enabled_items(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
[selection]
reboot = no
dc = yes
mix = yes

[dc]
FIO_CYCLES = 3
IGNORE_ERROR = no

[mix]
FIO_DISKS = sdb,sdc
""",
        encoding="utf-8",
    )

    selected, params = parse_items_file(config)

    assert selected == ["dc", "mix"]
    assert params["dc"]["FIO_CYCLES"] == "3"
    assert params["mix"]["FIO_DISKS"] == "sdb,sdc"


def test_parse_legacy_enable_blocks_still_work(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
[lawdisk]
enable = yes
IGNORE_ERROR = yes

[filesystem]
enable = no
""",
        encoding="utf-8",
    )

    selected, params = parse_items_file(config)

    assert selected == ["lawdisk"]
    assert params["lawdisk"]["IGNORE_ERROR"] == "yes"


def test_run_single_item_omits_allure_args_without_plugin(monkeypatch):
    captured = {}

    def fake_pytest_main(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(nvme_raid_test.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(nvme_raid_test.pytest, "main", fake_pytest_main)

    assert nvme_raid_test.run_single_item("lawdisk", {}, clean_allure=True) == 0

    args = captured["args"]
    assert "--clean-alluredir" not in args
    assert not any(arg.startswith("--alluredir=") for arg in args)
    assert "--junitxml=report_lawdisk.xml" in args


def test_run_single_item_supports_basic_io(monkeypatch):
    captured = {}

    def fake_pytest_main(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(nvme_raid_test.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(nvme_raid_test.pytest, "main", fake_pytest_main)

    assert nvme_raid_test.run_single_item("basic_io", {"IGNORE_ERROR": "no"}, clean_allure=False) == 0

    assert "--junitxml=report_basic_io.xml" in captured["args"]
    assert "test_items/test_smoke_06_basic_io.py" in captured["args"]


def test_main_stops_after_first_failed_item(monkeypatch):
    executed = []
    merged_calls = []

    monkeypatch.setattr(
        nvme_raid_test,
        "parse_items_file",
        lambda path: (["basic_io", "basic_rebuild_io"], {"basic_io": {}, "basic_rebuild_io": {}}),
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "prepare_case_workdir",
        lambda repo_root, item: str(Path(repo_root) / "cases" / item),
    )
    monkeypatch.setattr(nvme_raid_test, "collect_case_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        nvme_raid_test,
        "run_single_item",
        lambda item, params, clean_allure, work_dir=None: executed.append(item) or 1,
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "merge_junit_reports",
        lambda items, out_path: merged_calls.append(list(items)),
    )

    with pytest.raises(SystemExit) as exc:
        nvme_raid_test.main()

    assert exc.value.code == 1
    assert executed == ["basic_io"]
    assert merged_calls == [["basic_io"]]


def test_stop_monitor_escalates_to_kill(monkeypatch):
    calls = []
    checks = {"count": 0}
    monitor_main = nvme_raid_test.monitor_paths("/tmp/project")[0]

    def fake_run(cmd, stdout=None, stderr=None, check=False):
        calls.append(cmd)

        class Result:
            returncode = 0

        if cmd[:2] == ["pgrep", "-f"]:
            checks["count"] += 1
            # Stay alive through TERM wait, then disappear after KILL.
            Result.returncode = 1 if checks["count"] > 32 else 0
        return Result()

    monkeypatch.setattr(nvme_raid_test.subprocess, "run", fake_run)
    monkeypatch.setattr(nvme_raid_test.time, "sleep", lambda seconds: None)

    nvme_raid_test.stop_monitor_for_item("/tmp/project", wait_seconds=30)

    assert ["pkill", "-TERM", "-f", monitor_main] in calls
    assert ["pkill", "-KILL", "-f", monitor_main] in calls
