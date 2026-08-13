from ci.remote_workspace_path import case_workdir, remote_workspace_root, sanitize_segment


def test_sanitize_segment_strips_origin_and_unsafe_chars():
    assert sanitize_segment("origin/feature/foo bar") == "feature_foo_bar"
    assert sanitize_segment("") == "unknown"


def test_remote_workspace_root_separates_job_branch_and_build():
    path = remote_workspace_root(
        job_name="CI",
        branch="CI",
        build_number="9",
        kind="build",
    )
    assert path == "/root/Cyril/Jenkins/CI/CI/build-9"

    smoke = remote_workspace_root(
        job_name="SMOKE",
        branch="SMOKE",
        build_number="17010",
        kind="build",
    )
    assert smoke == "/root/Cyril/Jenkins/SMOKE/SMOKE/build-17010"

    restore = remote_workspace_root(
        job_name="CI",
        branch="main",
        build_number="3",
        kind="restore",
    )
    assert restore == "/root/Cyril/Jenkins/CI/main/restore-3"

    physical = remote_workspace_root(
        job_name="SMOKE",
        branch="SMOKE",
        build_number="17010",
        kind="physical",
    )
    assert physical == "/root/Cyril/Jenkins/SMOKE/SMOKE/physical-17010"


def test_case_workdir_nests_under_build_root():
    assert case_workdir("/root/Cyril/Jenkins/CI/CI/build-9", "basic_io") == (
        "/root/Cyril/Jenkins/CI/CI/build-9/cases/basic_io"
    )


def test_remote_workspace_root_falls_back_branch_to_job_name(monkeypatch):
    monkeypatch.delenv("BRANCH_NAME", raising=False)
    monkeypatch.delenv("GIT_BRANCH", raising=False)
    monkeypatch.delenv("CHANGE_BRANCH", raising=False)
    monkeypatch.setenv("JOB_BASE_NAME", "CI")
    monkeypatch.setenv("BUILD_NUMBER", "10")

    assert remote_workspace_root(job_name="CI", build_number="10") == (
        "/root/Cyril/Jenkins/CI/CI/build-10"
    )
