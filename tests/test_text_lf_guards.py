from pathlib import Path
from subprocess import check_output


def _blob_text(path: str) -> str:
    # Prefer index (survives Windows TSD worktree encryption).
    try:
        return check_output(["git", "cat-file", "-p", f":{path}"]).decode("utf-8")
    except Exception:
        return Path(path).read_text(encoding="utf-8")


def test_check_text_lf_script_exists_and_rejects_cr():
    source = _blob_text("ci/check_text_lf.py")
    assert "contains CR/CRLF" in source
    assert "restage_text_lf.py" in source
    assert "rev-parse" in source


def test_gitattributes_forces_lf_for_shell_and_python():
    text = _blob_text(".gitattributes")
    assert "*.sh text eol=lf" in text
    assert "*.py text eol=lf" in text
    assert "Jenkinsfile text eol=lf" in text


def test_restage_text_lf_normalizes_real_crlf_bytes():
    # Guard against PowerShell eating \\r\\n into no-ops in helpers.
    source = _blob_text("ci/restage_text_lf.py")
    assert '"\\r\\n"' in source or "'\\r\\n'" in source
    assert "replace(\"\\r\\n\", \"\\n\")" in source or "replace('\\r\\n', '\\n')" in source



def test_clear_script_in_index_has_no_cr():
    # Direct regression for: set: pipefail / invalid option name
    from subprocess import check_output

    blob = check_output(["git", "cat-file", "-p", ":ci/clear_8p_csd_flash.sh"])
    assert not blob.startswith(b"%TSD-Header-###%")
    assert b"\r" not in blob
    assert blob.splitlines()[1].startswith(b"set -euo pipefail")
