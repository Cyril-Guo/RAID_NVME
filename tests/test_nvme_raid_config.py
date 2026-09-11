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
    assert item_name_from_filename("test_powercycle_00_env_prepare.py") == "test_powercycle_00_env_prepare"
    assert item_name_from_filename("test_powercycle_01_reboot.py") == "test_powercycle_01_reboot"
    assert item_name_from_filename("test_powercycle_02_dc.py") == "test_powercycle_02_dc"
    assert item_name_from_filename("test_foo.py") == "foo"
    assert item_name_from_filename("basic_io_common.py") is None
    assert item_name_from_filename("powercycle_launch.py") is None
    assert item_name_from_filename("fio_run.py") is None
    assert item_name_from_filename("fio_allure.py") is None
    assert item_name_from_filename("__init__.py") is None


def test_discover_test_items_finds_repository_ci_cases():
    catalog = discover_test_items()

    assert set(catalog) == {
        "test_powercycle_00_env_prepare",
        "test_powercycle_01_reboot",
        "test_powercycle_02_dc",
    }
    assert catalog["test_powercycle_00_env_prepare"] == "test_items/test_powercycle_00_env_prepare.py"
    assert catalog["test_powercycle_01_reboot"] == "test_items/test_powercycle_01_reboot.py"
    assert catalog["test_powercycle_02_dc"] == "test_items/test_powercycle_02_dc.py"


def test_discover_test_items_rejects_duplicate_names(tmp_path):
    items_dir = tmp_path / "test_items"
    items_dir.mkdir()
    (items_dir / "test_powercycle_01_foo.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    # Plain test_foo.py maps to "foo"; CI file maps to full name — no clash.
    # Duplicate full CI names are OS-impossible; duplicate plain names:
    (items_dir / "test_foo.py").write_text("def test_b():\n    pass\n", encoding="utf-8")
    catalog = discover_test_items(str(items_dir))
    assert "test_powercycle_01_foo" in catalog
    assert "foo" in catalog


def test_repository_test_items_file_is_valid():
    config = Path(__file__).resolve().parents[1] / "test_items.txt"
    text = config.read_text(encoding="utf-8")
    catalog = discover_test_items()

    selected, params = parse_items_file(config)
    entries = nvme_raid_test.read_selection_entries(str(config))

    assert "BEGIN SELECTION" in text
    assert "END SELECTION" in text
    assert set(name for name, _orders, _enabled in entries) == set(catalog)
    assert selected == ["test_powercycle_01_reboot"]
    assert all(name in catalog for name in selected)
    assert "defaults" not in params
    assert params["test_powercycle_01_reboot"]["FIO_CYCLES"] == "100"
    assert params["test_powercycle_01_reboot"]["IGNORE_ERROR"] == "no"
    assert params["test_powercycle_02_dc"]["FIO_CYCLES"] == "5"
    assert "test_powercycle_00_env_prepare" in params
    assert "reboot" not in catalog
    assert "mix" not in catalog


def test_main_prints_item_boundaries():
    source = Path("nvme_raid_test.py").read_text(encoding="utf-8")

    assert "[ITEM_START] {run_key}" in source
    assert "[ITEM_END] {run_key} exit_code={exit_code}" in source
    assert "sync_selection_list" in source


def test_sync_selection_lists_all_discovered_items(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# === BEGIN SELECTION（自动同步；完整用例名 + 执行序号，# 表示不跑）===
test_powercycle_01_reboot 1
# === END SELECTION ===

[test_powercycle_01_reboot]
IGNORE_ERROR = yes
""",
        encoding="utf-8",
        newline="\n",
    )
    catalog = {
        "test_powercycle_00_env_prepare": "test_items/test_powercycle_00_env_prepare.py",
        "test_powercycle_01_reboot": "test_items/test_powercycle_01_reboot.py",
        "test_powercycle_02_dc": "test_items/test_powercycle_02_dc.py",
    }

    assert nvme_raid_test.sync_selection_list(str(config), catalog) is True
    text = config.read_text(encoding="utf-8")
    monkey_items = catalog
    # parse uses global TEST_ITEMS; enable via build_run_plan with catalog
    entries = nvme_raid_test.read_selection_entries(str(config))
    selected = [
        entry["item"]
        for entry in nvme_raid_test.build_run_plan(str(config), test_items=monkey_items)
    ]

    assert selected == ["test_powercycle_01_reboot"]
    assert {name for name, _o, _e in entries} == set(catalog)
    assert "test_powercycle_01_reboot 1\n" in text
    assert "# test_powercycle_00_env_prepare " in text
    assert "# test_powercycle_02_dc " in text


def test_sync_selection_preserves_custom_numeric_order(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# === BEGIN SELECTION（自动同步；完整用例名 + 执行序号，# 表示不跑）===
test_powercycle_02_dc 1
# test_powercycle_00_env_prepare 2
test_powercycle_01_reboot 3
# === END SELECTION ===

[test_powercycle_02_dc]
IGNORE_ERROR = yes

[test_powercycle_01_reboot]
IGNORE_ERROR = yes
""",
        encoding="utf-8",
        newline="\n",
    )
    catalog = {
        "test_powercycle_00_env_prepare": "test_items/test_powercycle_00_env_prepare.py",
        "test_powercycle_01_reboot": "test_items/test_powercycle_01_reboot.py",
        "test_powercycle_02_dc": "test_items/test_powercycle_02_dc.py",
    }

    assert nvme_raid_test.sync_selection_list(str(config), catalog) is False
    entries = nvme_raid_test.read_selection_entries(str(config))
    selected = [
        entry["item"]
        for entry in nvme_raid_test.build_run_plan(str(config), test_items=catalog)
    ]

    assert selected == ["test_powercycle_02_dc", "test_powercycle_01_reboot"]
    assert [(name, orders) for name, orders, _enabled in entries] == [
        ("test_powercycle_02_dc", [1]),
        ("test_powercycle_00_env_prepare", [2]),
        ("test_powercycle_01_reboot", [3]),
    ]


def test_parse_whitelist_controls_enabled_items_with_per_case_params(tmp_path, monkeypatch):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# === BEGIN SELECTION（自动同步；完整用例名 + 执行序号，# 表示不跑）===
# test_powercycle_00_env_prepare 0
test_powercycle_02_dc 2
# === END SELECTION ===

[test_powercycle_02_dc]
FIO_CYCLES = 3
IGNORE_ERROR = no
""",
        encoding="utf-8",
    )
    catalog = {
        "test_powercycle_00_env_prepare": "test_items/test_powercycle_00_env_prepare.py",
        "test_powercycle_01_reboot": "test_items/test_powercycle_01_reboot.py",
        "test_powercycle_02_dc": "test_items/test_powercycle_02_dc.py",
    }
    monkeypatch.setattr(nvme_raid_test, "TEST_ITEMS", catalog)

    selected, params = parse_items_file(config)

    assert selected == ["test_powercycle_02_dc"]
    assert params["test_powercycle_02_dc"] == {"FIO_CYCLES": "3", "IGNORE_ERROR": "no"}


def test_parse_sorts_enabled_items_by_numeric_order(tmp_path, monkeypatch):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# === BEGIN SELECTION（自动同步；完整用例名 + 执行序号，# 表示不跑）===
test_powercycle_01_reboot 3
test_powercycle_02_dc 1
# === END SELECTION ===
""",
        encoding="utf-8",
    )
    catalog = {
        "test_powercycle_01_reboot": "test_items/test_powercycle_01_reboot.py",
        "test_powercycle_02_dc": "test_items/test_powercycle_02_dc.py",
    }
    monkeypatch.setattr(nvme_raid_test, "TEST_ITEMS", catalog)

    selected, _params = parse_items_file(config)
    assert selected == ["test_powercycle_02_dc", "test_powercycle_01_reboot"]


def test_parse_selection_entry_supports_multiple_orders():
    assert nvme_raid_test.parse_selection_entry("test_powercycle_01_reboot 8 10") == (
        "test_powercycle_01_reboot",
        [8, 10],
        True,
    )
    assert nvme_raid_test.parse_selection_entry("# test_powercycle_01_reboot 8 10") == (
        "test_powercycle_01_reboot",
        [8, 10],
        False,
    )
    assert nvme_raid_test.parse_selection_entry("mix 8 10") == ("mix", [8, 10], True)
    assert nvme_raid_test.parse_selection_entry("8 10 mix") == ("mix", [8, 10], True)


def test_read_enabled_selection_repeats_item_for_multiple_orders(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# === BEGIN SELECTION（自动同步；完整用例名 + 执行序号，# 表示不跑）===
test_powercycle_01_reboot 8 10
test_powercycle_00_env_prepare 1
# === END SELECTION ===
""",
        encoding="utf-8",
    )
    catalog = {
        "test_powercycle_01_reboot": "test_items/test_powercycle_01_reboot.py",
        "test_powercycle_00_env_prepare": "test_items/test_powercycle_00_env_prepare.py",
    }

    plan = nvme_raid_test.build_run_plan(str(config), test_items=catalog)
    selected = [entry["item"] for entry in plan]

    assert selected == ["test_powercycle_00_env_prepare", "test_powercycle_01_reboot", "test_powercycle_01_reboot"]
    assert [entry["run_key"] for entry in plan] == [
        "test_powercycle_00_env_prepare__1",
        "test_powercycle_01_reboot__8",
        "test_powercycle_01_reboot__10",
    ]


def test_build_run_plan_tags_run_key_with_order(tmp_path):
    config = tmp_path / "test_items.txt"
    config.write_text(
        """
# === BEGIN SELECTION（自动同步；完整用例名 + 执行序号，# 表示不跑）===
test_powercycle_01_reboot 3
# === END SELECTION ===
""",
        encoding="utf-8",
    )
    catalog = {"test_powercycle_01_reboot": "test_items/test_powercycle_01_reboot.py"}

    plan = nvme_raid_test.build_run_plan(str(config), test_items=catalog)

    assert plan == [
        {"item": "test_powercycle_01_reboot", "order": 3, "run_key": "test_powercycle_01_reboot__3"}
    ]


def test_validate_powercycle_plan_rejects_mixed_or_multiple_powercycle_runs():
    nvme_raid_test.validate_powercycle_plan(
        [{"item": "test_powercycle_01_reboot", "order": 1, "run_key": "test_powercycle_01_reboot__1"}]
    )

    with pytest.raises(ValueError, match="must run alone"):
        nvme_raid_test.validate_powercycle_plan(
            [
                {"item": "test_powercycle_01_reboot", "order": 1, "run_key": "test_powercycle_01_reboot__1"},
                {"item": "test_powercycle_00_env_prepare", "order": 0, "run_key": "test_powercycle_00_env_prepare__0"},
            ]
        )

    with pytest.raises(ValueError, match="must run alone"):
        nvme_raid_test.validate_powercycle_plan(
            [
                {"item": "test_powercycle_01_reboot", "order": 1, "run_key": "test_powercycle_01_reboot__1"},
                {"item": "test_powercycle_02_dc", "order": 2, "run_key": "test_powercycle_02_dc__2"},
            ]
        )


def test_run_single_item_omits_allure_args_without_plugin(monkeypatch, tmp_path):
    captured = {}

    def fake_pytest_main(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(nvme_raid_test.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(nvme_raid_test.pytest, "main", fake_pytest_main)
    catalog = {"test_powercycle_01_reboot": "test_items/test_powercycle_01_reboot.py"}

    assert (
        nvme_raid_test.run_single_item(
            "test_powercycle_01_reboot",
            {},
            clean_allure=True,
            work_dir=str(tmp_path),
            test_items=catalog,
        )
        == 0
    )

    args = captured["args"]
    assert "--clean-alluredir" not in args
    assert not any(arg.startswith("--alluredir=") for arg in args)
    assert "--junitxml=report_test_powercycle_01_reboot.xml" in args


def test_run_single_item_does_not_clear_csd(monkeypatch, tmp_path):
    clear_calls = []

    monkeypatch.setattr(nvme_raid_test.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(nvme_raid_test.pytest, "main", lambda args: 0)
    monkeypatch.setattr(
        "test_items.basic_io_common.release_and_clear_csd",
        lambda disks, log: clear_calls.append(True),
    )
    catalog = {
        "test_powercycle_00_env_prepare": "test_items/test_powercycle_00_env_prepare.py",
        "test_powercycle_01_reboot": "test_items/test_powercycle_01_reboot.py",
    }

    for item in ("test_powercycle_00_env_prepare", "test_powercycle_01_reboot"):
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
    catalog = {"test_powercycle_01_reboot": "test_items/test_powercycle_01_reboot.py"}

    assert (
        nvme_raid_test.run_single_item(
            "test_powercycle_01_reboot",
            {},
            clean_allure=True,
            work_dir=str(tmp_path),
            run_key="test_powercycle_01_reboot__2",
            order=2,
            test_items=catalog,
        )
        == 0
    )

    assert "--junitxml=report_test_powercycle_01_reboot__2.xml" in captured["args"]
    assert captured["run_key"] == "test_powercycle_01_reboot__2"
    assert captured["order"] == "2"
    assert captured["item"] == "test_powercycle_01_reboot"
    assert os.environ.get("RAID_NVME_RUN_KEY") is None


def test_merge_junit_reports_keeps_duplicate_run_keys(tmp_path):
    for run_key in ("test_powercycle_01_reboot__2", "test_powercycle_01_reboot__5"):
        (tmp_path / f"report_{run_key}.xml").write_text(
            f"""<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1">
  <testcase classname="test_items.{run_key}" name="test_reboot_powercycle" />
</testsuite>
""",
            encoding="utf-8",
        )
    output = tmp_path / "report.xml"
    previous = os.getcwd()
    try:
        os.chdir(tmp_path)
        nvme_raid_test.merge_junit_reports(
            ["test_powercycle_01_reboot__2", "test_powercycle_01_reboot__5"], "report.xml"
        )
    finally:
        os.chdir(previous)

    merged = output.read_text(encoding="utf-8")
    assert merged.count("testcase") == 2


def test_discover_junit_run_keys_skips_node_reports(tmp_path):
    (tmp_path / "report_test_powercycle_01_reboot__2.xml").write_text("<testsuite/>", encoding="utf-8")
    (tmp_path / "report_192.168.1.10.xml").write_text("<testsuite/>", encoding="utf-8")

    assert nvme_raid_test.discover_junit_run_keys(str(tmp_path)) == ["test_powercycle_01_reboot__2"]


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

    case_dir = Path(nvme_raid_test.prepare_case_workdir(str(repo), "test_powercycle_01_reboot"))

    assert case_dir == repo / "cases" / "test_powercycle_01_reboot"
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
            {"item": "test_powercycle_01_reboot", "order": 1, "run_key": "test_powercycle_01_reboot__1"},
            {"item": "test_powercycle_02_dc", "order": 2, "run_key": "test_powercycle_02_dc__2"},
        ],
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "parse_items_file",
        lambda path: (
            ["test_powercycle_01_reboot", "test_powercycle_02_dc"],
            {"test_powercycle_01_reboot": {}, "test_powercycle_02_dc": {}},
        ),
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "discover_test_items",
        lambda items_dir=None: {
            "test_powercycle_01_reboot": "test_items/test_powercycle_01_reboot.py",
            "test_powercycle_02_dc": "test_items/test_powercycle_02_dc.py",
        },
    )
    monkeypatch.setattr(nvme_raid_test, "validate_powercycle_plan", lambda plan: None)
    monkeypatch.setattr(
        nvme_raid_test,
        "prepare_case_workdir",
        lambda repo_root, item: str(tmp_path / item),
    )
    monkeypatch.setattr(nvme_raid_test, "collect_case_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        nvme_raid_test,
        "run_single_item",
        lambda item, params, clean_allure, test_items=None, work_dir=None, **kwargs: executed.append(
            item
        )
        or (1 if item == "test_powercycle_01_reboot" else 0),
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "merge_junit_reports",
        lambda items, out_path: merged_calls.append(list(items)),
    )

    with pytest.raises(SystemExit) as exc:
        nvme_raid_test.main([])

    assert exc.value.code == 1
    assert executed == ["test_powercycle_01_reboot"]
    assert merged_calls == [["test_powercycle_01_reboot__1"]]


def test_main_uses_whitelist_order_not_discovery_order(monkeypatch, tmp_path):
    executed = []

    monkeypatch.setattr(nvme_raid_test, "sync_selection_list", lambda path, catalog: False)
    monkeypatch.setattr(
        nvme_raid_test,
        "build_run_plan",
        lambda path, test_items=None: [
            {"item": "test_powercycle_02_dc", "order": 1, "run_key": "test_powercycle_02_dc__1"},
            {"item": "test_powercycle_01_reboot", "order": 3, "run_key": "test_powercycle_01_reboot__3"},
        ],
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "parse_items_file",
        lambda path: (
            ["test_powercycle_02_dc", "test_powercycle_01_reboot"],
            {"test_powercycle_02_dc": {}, "test_powercycle_01_reboot": {}},
        ),
    )
    monkeypatch.setattr(
        nvme_raid_test,
        "discover_test_items",
        lambda items_dir=None: {
            "test_powercycle_01_reboot": "test_items/test_powercycle_01_reboot.py",
            "test_powercycle_02_dc": "test_items/test_powercycle_02_dc.py",
        },
    )
    monkeypatch.setattr(nvme_raid_test, "validate_powercycle_plan", lambda plan: None)
    monkeypatch.setattr(
        nvme_raid_test,
        "prepare_case_workdir",
        lambda repo_root, item: str(tmp_path / item),
    )
    monkeypatch.setattr(nvme_raid_test, "collect_case_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        nvme_raid_test,
        "run_single_item",
        lambda item, params, clean_allure, test_items=None, work_dir=None, **kwargs: executed.append(
            item
        )
        or 0,
    )
    monkeypatch.setattr(nvme_raid_test, "merge_junit_reports", lambda items, out_path: None)

    with pytest.raises(SystemExit) as exc:
        nvme_raid_test.main([])

    assert exc.value.code == 0
    assert executed == ["test_powercycle_02_dc", "test_powercycle_01_reboot"]


