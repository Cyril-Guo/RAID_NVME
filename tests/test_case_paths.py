from pathlib import Path

from test_items.case_paths import case_root, io_stress_dir


def test_case_paths_prefer_raid_nvme_case_root(monkeypatch, tmp_path):
    case = tmp_path / "cases" / "mix"
    (case / "IO_Stress").mkdir(parents=True)
    shared = tmp_path / "IO_Stress"
    shared.mkdir()
    monkeypatch.setenv("RAID_NVME_CASE_ROOT", str(case))
    monkeypatch.chdir(tmp_path)

    assert Path(case_root()) == case.resolve()
    assert Path(io_stress_dir()) == (case / "IO_Stress").resolve()


def test_case_paths_prefer_cwd_when_env_missing(monkeypatch, tmp_path):
    case = tmp_path / "cases" / "mix"
    (case / "IO_Stress").mkdir(parents=True)
    monkeypatch.delenv("RAID_NVME_CASE_ROOT", raising=False)
    monkeypatch.chdir(case)

    assert Path(io_stress_dir()) == (case / "IO_Stress").resolve()


def test_nvme_raid_test_sets_case_root_env():
    source = Path("nvme_raid_test.py").read_text(encoding="utf-8")
    assert 'os.environ["RAID_NVME_CASE_ROOT"]' in source
    assert "RAID_NVME_CASE_ROOT" in Path("test_items/case_paths.py").read_text(encoding="utf-8")
