from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FLASH_CLEAR_SCRIPT = REPO_ROOT / "ci" / "flash-clear.sh"
CLEAR_8P_SCRIPT = REPO_ROOT / "ci" / "clear_8p_csd_flash.sh"


def test_flash_clear_includes_cache_clear_opcode():
    text = FLASH_CLEAR_SCRIPT.read_text(encoding="utf-8")
    assert "CACHE_CLEAR_OPCODE" in text
    assert 'CACHE_CLEAR_OPCODE="${CACHE_CLEAR_OPCODE:-0xD8}"' in text
    assert "Cache clear" in text


def test_flash_clear_runs_cache_clear_after_flash_write():
    text = FLASH_CLEAR_SCRIPT.read_text(encoding="utf-8")
    loop_section = text.split("for dev in", 1)[1]
    write_idx = loop_section.index("FLASH_WRITE_OPCODE")
    cache_idx = loop_section.index("CACHE_CLEAR_OPCODE")
    assert write_idx < cache_idx


def test_clear_8p_doc_mentions_cache_clear():
    text = CLEAR_8P_SCRIPT.read_text(encoding="utf-8")
    assert "0xD8" in text
    assert "Cache clear" in text
