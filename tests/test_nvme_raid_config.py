from pathlib import Path
import os

import pytest

import nvme_raid_test
from nvme_raid_test import (
    discover_test_items,
    item_name_from_filename,
    parse_items_file,
)


def test_item_name_from_filename_supports_ci_and_plain_patterns():
    assert item_name_from_filename("test_ci_01_lawdisk.py") == "test_ci_01_lawdisk"
    assert item_name_from_filename("test_ci_03_mix_4k.py") == "test_ci_03_mix_4k"
    assert item_name_from_filename("test_foo.py") == "foo"
    assert item_name_from_filename("basic_io_common.py") is None
    assert item_name_from_filename("test_basic_io_common.py") is None
    assert item_name_from_filename("powercycle_launch.py") is None
    assert item_name_from_filename("fio_run.py") is None
    assert item_name_from_filename("fio_allure.py") is None
    assert item_name_from_filename("random_io_plan.py") is None
    assert item_name_from_filename("__init__.py") is None


def test_discover_test_items_finds_repository_ci_cases():
    catalog = discover_test_items()

    assert catalog["test_ci_00_env_prepare"] == "test_items/test_ci_00_env_prepare.py"
    assert catalog["test_ci_01_lawdisk"] == "test_items/test_ci_01_lawdisk.py"
    assert catalog["test_ci_02_filesystem"] == "test_items/test_ci_02_filesystem.py"
    assert catalog["test_ci_03_mix_4k"] == "test_items/test_ci_03_mix_4k.py"
    assert catalog["test_ci_04_mix_512"] == "test_items/test_ci_04_mix_512.py"
    assert catalog["test_ci_05_random_io_4k"] == "test_items/test_ci_05_random_io_4k.py"
    assert catalog["test_ci_06_random_io_512"] == "test_items/test_ci_06_random_io_512.py"
    assert set(catalog) == {
        "test_ci_00_env_prepare",
        "test_ci_01_lawdisk",
        "test_ci_02_filesystem",
        "test_ci_03_mix_4k",
        "test_ci_04_mix_512",
        "test_ci_05_random_io_4k",
        "test_ci_06_random_io_512",
    }



def test_discover_test_items_rejects_duplicate_names(tmp_path):
    items_dir = tmp_path / "test_items"
    items_dir.mkdir()
    (items_dir / "test_ci_01_foo.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    (items_dir / "test_foo.py").write_text("def test_b():\n    pass\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate test item name 'foo'"):
        discover_test_items(str(items_dir))


def test_repository_test_items_file_is_valid():
    config = Path(__file__).resolve().parents[1] / "test_items.txt"
    text = config.read_text(encoding="utf-8")
    catalog = discover_test_items()

    selected, params = parse_items_file(config)
    entries = nvme_raid_test.read_selection_entries(str(config))

    assert "BEGIN SELECTION" in text
    assert "END SELECTION" in text
    assert [name for name, _orders, _enabled in entries]
    assert set(name for name, _orders, _enabled in entries) == set(catalog)
    assert selected
    assert all(name in catalog for name in selected)
    assert "defaults" not in params
    assert params["test_ci_01_lawdisk"]["IGNORE_ERROR"] == "yes"
    assert params["test_ci_01_lawdisk"]["FIO_CONFIG"] == "Input_Config_lawdisk.csv"
    assert params["test_ci_02_filesystem"]["FIO_CONFIG"] == "Input_Config_filesystem.csv"
    assert params["test_ci_03_mix_4k"]["FIO_CONFIG"] == "Input_Config_mix_4k.csv"
    assert params["test_ci_03_mix_4k"]["MIX_FAIL_ON_ANY"].strip().lower() in ("yes", "no")
    assert params["test_ci_02_filesystem"]["FIO_RUNTIME"] == "43200"
    assert "FIO_RUNTIME" in nvme_raid_test.ALLOWED_PARAM_KEYS
    assert params["test_ci_05_random_io_4k"]["FIO_CONFIG"] == "Input_Config_random_io_4k.csv"
    assert "FIO_CYCLES" not in params["test_ci_01_lawdisk"]
    assert "test_ci_00_env_prepare" in params
    assert "reboot" not in catalog
    assert "lawdisk_4k" not in catalog
    assert "lawdisk_512" not in catalog
    assert "filesystem_4k" not in catalog
    assert "mix_4k" not in catalog


def test_main_prints_item_boundaries():
    source = Path("nvme_raid_test.py").read_text(encoding="utf-8")

    assert "[ITEM_START] {run_key}" in source
    assert "[ITEM_END] {run_key} exit_code={exit_code}" in source
    assert "sync_selection_list" in source
    assert "[defaults]" not in Path("test_items.txt").read_text(encoding="utf-8")


def test_sync_selection_lists_all_discovered_items(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# header
# === BEGIN SELECTION（自动同步；完整用例名 + 执行序号，# 表示不跑）===
test_ci_01_lawdisk 3
# test_ci_03_mix_4k 5
# === END SELECTION ===

[test_ci_01_lawdisk]
IGNORE_ERROR = no

[test_ci_03_mix_4k]
IGNORE_ERROR = no
""",
        encoding="utf-8",
        newline="\n",
    )
    catalog = {
        "test_ci_01_lawdisk": "test_items/test_ci_01_lawdisk.py",
        "test_ci_01_lawdisk": "test_items/test_ci_01_lawdisk.py",
        "test_ci_02_filesystem": "test_items/test_ci_02_filesystem.py",
        "test_ci_03_mix_4k": "test_items/test_ci_03_mix_4k.py",
    }

    assert nvme_raid_test.sync_selection_list(str(config), catalog) is True
    text = config.read_text(encoding="utf-8")
    selected, _params = parse_items_file(config)
    entries = nvme_raid_test.read_selection_entries(str(config))

    assert selected == ["test_ci_01_lawdisk"]
    assert [(name, orders, enabled) for name, orders, enabled in entries] == [
        ("test_ci_01_lawdisk", [2], False),
        ("test_ci_01_lawdisk", [3], True),
        ("test_ci_03_mix_4k", [5], False),
        ("test_ci_02_filesystem", [6], False),
    ]
    assert "test_ci_01_lawdisk 3\n" in text
    assert "# test_ci_01_lawdisk 2\n" in text
    assert "# test_ci_03_mix_4k 5\n" in text
    assert "# test_ci_02_filesystem 6\n" in text



def test_sync_selection_preserves_custom_numeric_order(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# === BEGIN SELECTION（自动同步；完整用例名 + 执行序号，# 表示不跑）===
test_ci_03_mix_4k 1
# test_ci_02_filesystem 2
test_ci_01_lawdisk 3
# test_ci_01_lawdisk 4
# === END SELECTION ===

[test_ci_03_mix_4k]
IGNORE_ERROR = no

[test_ci_01_lawdisk]
IGNORE_ERROR = no
""",
        encoding="utf-8",
        newline="\n",
    )
    catalog = {
        "test_ci_01_lawdisk": "test_items/test_ci_01_lawdisk.py",
        "test_ci_01_lawdisk": "test_items/test_ci_01_lawdisk.py",
        "test_ci_02_filesystem": "test_items/test_ci_02_filesystem.py",
        "test_ci_03_mix_4k": "test_items/test_ci_03_mix_4k.py",
    }

    assert nvme_raid_test.sync_selection_list(str(config), catalog) is False
    selected, _params = parse_items_file(config)
    entries = nvme_raid_test.read_selection_entries(str(config))

    assert selected == ["test_ci_03_mix_4k", "test_ci_01_lawdisk"]
    assert [(name, orders) for name, orders, _enabled in entries] == [
        ("test_ci_03_mix_4k", [1]),
        ("test_ci_02_filesystem", [2]),
        ("test_ci_01_lawdisk", [3]),
        ("test_ci_01_lawdisk", [4]),
    ]



def test_parse_whitelist_controls_enabled_items_with_per_case_params(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# === BEGIN SELECTION（自动同步；完整用例名 + 执行序号，# 表示不跑）===
# test_ci_01_lawdisk 1
test_ci_01_lawdisk 2
test_ci_03_mix_4k 5
# === END SELECTION ===

[test_ci_01_lawdisk]
FIO_CYCLES = 3
IGNORE_ERROR = no

[test_ci_03_mix_4k]
FIO_DISKS = sdb,sdc
STRESS_MONITOR = yes
""",
        encoding="utf-8",
    )

    selected, params = parse_items_file(config)

    assert selected == ["test_ci_01_lawdisk", "test_ci_03_mix_4k"]
    assert params["test_ci_01_lawdisk"] == {"FIO_CYCLES": "3", "IGNORE_ERROR": "no"}
    assert params["test_ci_03_mix_4k"] == {"FIO_DISKS": "sdb,sdc", "STRESS_MONITOR": "yes"}
    assert "FIO_CYCLES" not in params["test_ci_03_mix_4k"]



def test_parse_sorts_enabled_items_by_numeric_order(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# === BEGIN SELECTION（自动同步；完整用例名 + 执行序号，# 表示不跑）===
test_ci_03_mix_4k 5
test_ci_01_lawdisk 3
test_ci_01_lawdisk 1
# === END SELECTION ===

[test_ci_03_mix_4k]
IGNORE_ERROR = no

[test_ci_01_lawdisk]
IGNORE_ERROR = no

[test_ci_01_lawdisk]
FIO_CYCLES = 10
""",
        encoding="utf-8",
    )

    selected, _params = parse_items_file(config)

    assert selected == ["test_ci_01_lawdisk", "test_ci_01_lawdisk", "test_ci_03_mix_4k"]



def test_parse_selection_entry_supports_multiple_orders():
    assert nvme_raid_test.parse_selection_entry("test_ci_03_mix_4k 8 10") == (
        "test_ci_03_mix_4k",
        [8, 10],
        True,
    )
    assert nvme_raid_test.parse_selection_entry("# test_ci_03_mix_4k 8 10") == (
        "test_ci_03_mix_4k",
        [8, 10],
        False,
    )
    assert nvme_raid_test.parse_selection_entry("test_ci_03_mix_4k 1") == (
        "test_ci_03_mix_4k",
        [1],
        True,
    )
    # order-first still accepted
    assert nvme_raid_test.parse_selection_entry("8 10 test_ci_03_mix_4k") == (
        "test_ci_03_mix_4k",
        [8, 10],
        True,
    )



def test_read_enabled_selection_repeats_item_for_multiple_orders(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# === BEGIN SELECTION（自动同步；完整用例名 + 执行序号，# 表示不跑）===
test_ci_03_mix_4k 8 10
test_ci_03_mix_4k 1
test_ci_05_random_io_4k 9
# === END SELECTION ===

[test_ci_03_mix_4k]
IGNORE_ERROR = no

[test_ci_03_mix_4k]
IGNORE_ERROR = no

[test_ci_05_random_io_4k]
IGNORE_ERROR = no
""",
        encoding="utf-8",
    )
    catalog = {
        "test_ci_03_mix_4k": "test_items/test_ci_03_mix_4k.py",
        "test_ci_05_random_io_4k": "test_items/test_ci_05_random_io_4k.py",
    }

    selected = nvme_raid_test.read_enabled_selection(str(config))
    plan = nvme_raid_test.build_run_plan(str(config), test_items=catalog)

    assert selected == ["test_ci_03_mix_4k", "test_ci_03_mix_4k", "test_ci_05_random_io_4k", "test_ci_03_mix_4k"]
    assert [entry["item"] for entry in plan] == selected
    assert [entry["run_key"] for entry in plan] == [
        "test_ci_03_mix_4k__1",
        "test_ci_03_mix_4k__8",
        "test_ci_05_random_io_4k__9",
        "test_ci_03_mix_4k__10",
    ]


def test_build_run_plan_tags_run_key_with_order(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# === BEGIN SELECTION（自动同步；完整用例名 + 执行序号，# 表示不跑）===
test_ci_01_lawdisk 3
# === END SELECTION ===

[test_ci_01_lawdisk]
IGNORE_ERROR = no
""",
        encoding="utf-8",
    )
    catalog = {"test_ci_01_lawdisk": "test_items/test_ci_01_lawdisk.py"}

    plan = nvme_raid_test.build_run_plan(str(config), test_items=catalog)

    assert plan == [{"item": "test_ci_01_lawdisk", "order": 3, "run_key": "test_ci_01_lawdisk__3"}]


def test_validate_powercycle_plan_rejects_mixed_or_multiple_powercycle_runs():
    nvme_raid_test.validate_powercycle_plan(
        [{"item": "test_ci_01_reboot", "order": 1, "run_key": "test_ci_01_reboot__1"}]
    )

    with pytest.raises(ValueError, match="must run alone"):
        nvme_raid_test.validate_powercycle_plan(
            [
                {"item": "test_ci_01_reboot", "order": 1, "run_key": "test_ci_01_reboot__1"},
                {"item": "test_ci_03_mix_4k", "order": 2, "run_key": "test_ci_03_mix_4k__2"},
            ]
        )

    with pytest.raises(ValueError, match="must run alone"):
        nvme_raid_test.validate_powercycle_plan(
            [
                {"item": "test_ci_01_reboot", "order": 1, "run_key": "test_ci_01_reboot__1"},
                {"item": "test_ci_02_dc", "order": 2, "run_key": "test_ci_02_dc__2"},
            ]
        )


def test_run_single_item_omits_allure_args_without_plugin(monkeypatch, tmp_path):
    captured = {}

    def fake_pytest_main(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(nvme_raid_test.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(nvme_raid_test.pytest, "main", fake_pytest_main)

    assert nvme_raid_test.run_single_item(
        "test_ci_01_lawdisk", {}, clean_allure=True, work_dir=str(tmp_path)
    ) == 0

    args = captured["args"]
    assert "--clean-alluredir" not in args
    assert not any(arg.startswith("--alluredir=") for arg in args)
    assert "--junitxml=report_test_ci_01_lawdisk.xml" in args


def test_run_single_item_does_not_clear_csd(monkeypatch, tmp_path):
    clear_calls = []

    monkeypatch.setattr(nvme_raid_test.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(nvme_raid_test.pytest, "main", lambda args: 0)
    monkeypatch.setattr(
        "test_items.basic_io_common.release_and_clear_csd",
        lambda disks, log: clear_calls.append(True),
    )
    catalog = {
        "test_ci_03_mix_4k": "test_items/test_ci_03_mix_4k.py",
        "test_ci_05_random_io_4k": "test_items/test_ci_05_random_io_4k.py",
        "test_ci_00_env_prepare": "test_items/test_ci_00_env_prepare.py",
    }

    for item in ("test_ci_03_mix_4k", "test_ci_05_random_io_4k", "test_ci_00_env_prepare"):
        clear_calls.clear()
        assert (
            nvme_raid_test.run_single_item(
                item, {}, clean_allure=False, work_dir=str(tmp_path), test_items=catalog
            )
            == 0
        )
        assert clear_calls == [], item


def test_run_single_item_uses_run_key_for_junit_and_env(monkeypatch, tmp_path):
    captured = {}

    def fake_pytest_main(args):
        captured["args"] = args
        captured["run_key"] = os.environ.get("RAID_NVME_RUN_KEY")
        captured["order"] = os.environ.get("RAID_NVME_RUN_ORDER")
        captured["item"] = os.environ.get("RAID_NVME_ITEM")
        return 0

    monkeypatch.setattr(nvme_raid_test.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(nvme_raid_test.pytest, "main", fake_pytest_main)

    assert nvme_raid_test.run_single_item(
        "test_ci_01_lawdisk",
        {},
        clean_allure=True,
        work_dir=str(tmp_path),
        run_key="lawdisk__2",
        order=2,
    ) == 0

    assert "--junitxml=report_lawdisk__2.xml" in captured["args"]
    assert captured["run_key"] == "lawdisk__2"
    assert captured["order"] == "2"
    assert captured["item"] == "test_ci_01_lawdisk"
    assert os.environ.get("RAID_NVME_RUN_KEY") is None


def test_merge_junit_reports_keeps_duplicate_run_keys(tmp_path):
    for run_key in ("lawdisk__2", "lawdisk__5"):
        (tmp_path / f"report_{run_key}.xml").write_text(
            f"""<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1">
  <testcase classname="test_items.{run_key}" name="test_lawdiskstress" />
</testsuite>
""",
            encoding="utf-8",
        )
    output = tmp_path / "report.xml"
    previous = os.getcwd()
    try:
        os.chdir(tmp_path)
        nvme_raid_test.merge_junit_reports(["lawdisk__2", "lawdisk__5"], "report.xml")
    finally:
        os.chdir(previous)

    merged = output.read_text(encoding="utf-8")
    assert merged.count("testcase") == 2


def test_discover_junit_run_keys_skips_node_reports(tmp_path):
    (tmp_path / "report_lawdisk__2.xml").write_text("<testsuite/>", encoding="utf-8")
    (tmp_path / "report_192.168.1.10.xml").write_text("<testsuite/>", encoding="utf-8")

    assert nvme_raid_test.discover_junit_run_keys(str(tmp_path)) == ["lawdisk__2"]


def test_prepare_case_workdir_isolates_io_stress(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "nvme_raid_test.py").write_text("print('ok')\n", encoding="utf-8")
    io_stress = repo / "IO_Stress"
    io_stress.mkdir()
    (io_stress / "Fio_All.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (io_stress / "log").mkdir()
    (io_stress / "log" / "old.log").write_text("old\n", encoding="utf-8")
    (repo / "test_items").mkdir()
    (repo / "cases").mkdir()

    case_dir = Path(nvme_raid_test.prepare_case_workdir(str(repo), "test_ci_03_mix_4k"))

    assert case_dir == repo / "cases" / "test_ci_03_mix_4k"
    assert (case_dir / "nvme_raid_test.py").exists()
    assert (case_dir / "IO_Stress" / "Fio_All.sh").is_file()
    assert not (case_dir / "IO_Stress" / "log" / "old.log").exists()
    assert (case_dir / "IO_Stress" / "log").is_dir()


def test_main_stops_after_first_failed_item(monkeypatch, tmp_path):
    executed = []
    merged_calls = []

    monkeypatch.setattr(nvme_raid_test, "sync_selection_list", lambda path, catalog: False)
    monkeypatch.setattr(
        nvme_raid_test,
        "build_run_plan",
        lambda path, test_items=None: [
            {"item": "test_ci_01_lawdisk", "order": 3, "run_key": "test_ci_01_lawdisk"},
            {"item": "test_ci_03_mix_4k", "order": 5, "run_key": "test_ci_03_mix_4k"},
        ],
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "parse_items_file",
        lambda path: (["test_ci_01_lawdisk", "test_ci_03_mix_4k"], {"test_ci_01_lawdisk": {}, "test_ci_03_mix_4k": {}}),
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "discover_test_items",
        lambda items_dir=None: {
            "test_ci_01_lawdisk": "test_items/test_ci_01_lawdisk.py",
            "test_ci_03_mix_4k": "test_items/test_ci_03_mix_4k.py",
        },
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "prepare_case_workdir",
        lambda repo_root, item: str(tmp_path / item),
    )
    monkeypatch.setattr(nvme_raid_test, "collect_case_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        nvme_raid_test,
        "run_single_item",
        lambda item, params, clean_allure, test_items=None, work_dir=None, **kwargs: executed.append(item) or (1 if item == "test_ci_01_lawdisk" else 0),
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "merge_junit_reports",
        lambda items, out_path: merged_calls.append(list(items)),
    )

    with pytest.raises(SystemExit) as exc:
        nvme_raid_test.main([])

    assert exc.value.code == 1
    assert executed == ["test_ci_01_lawdisk"]
    assert merged_calls == [["test_ci_01_lawdisk"]]


def test_main_uses_whitelist_order_not_discovery_order(monkeypatch, tmp_path):
    executed = []

    monkeypatch.setattr(nvme_raid_test, "sync_selection_list", lambda path, catalog: False)
    monkeypatch.setattr(
        nvme_raid_test,
        "build_run_plan",
        lambda path, test_items=None: [
            {"item": "test_ci_03_mix_4k", "order": 1, "run_key": "test_ci_03_mix_4k"},
            {"item": "test_ci_01_lawdisk", "order": 3, "run_key": "test_ci_01_lawdisk"},
        ],
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "parse_items_file",
        lambda path: (["test_ci_03_mix_4k", "test_ci_01_lawdisk"], {"test_ci_03_mix_4k": {}, "test_ci_01_lawdisk": {}}),
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "discover_test_items",
        lambda items_dir=None: {
            "test_ci_01_lawdisk": "test_items/test_ci_01_lawdisk.py",
            "test_ci_03_mix_4k": "test_items/test_ci_03_mix_4k.py",
        },
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "prepare_case_workdir",
        lambda repo_root, item: str(tmp_path / item),
    )
    monkeypatch.setattr(nvme_raid_test, "collect_case_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        nvme_raid_test,
        "run_single_item",
        lambda item, params, clean_allure, test_items=None, work_dir=None, **kwargs: executed.append(item) or 0,
    )
    monkeypatch.setattr(nvme_raid_test, "merge_junit_reports", lambda items, out_path: None)

    with pytest.raises(SystemExit) as exc:
        nvme_raid_test.main([])

    assert exc.value.code == 0
    assert executed == ["test_ci_03_mix_4k", "test_ci_01_lawdisk"]


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
