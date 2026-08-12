"""Lightweight parser checks mirroring MachineCheck link/AER extraction rules."""

import re


def extract_link_field(text, section, field):
    pattern = re.compile(
        rf"^[ \t]*{re.escape(section)}:.*?\b{re.escape(field)}[ \t]+([^,\n]+)",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        return ""
    value = match.group(1).strip()
    value = re.sub(r"\s*\(.*\)$", "", value)
    return value


def extract_aer_field(text, section):
    pattern = re.compile(rf"^[ \t]*{re.escape(section)}:[ \t]*(.*)$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    return " ".join(match.group(1).split())


SAMPLE = """
e1:00.0 Non-Volatile memory controller: Shenzhen DAPU Microelectronics Co., Ltd NVMe SSD Controller DPU600
        LnkCap: Port #0, Speed 16GT/s, Width x4, ASPM L1, Exit Latency L0s unlimited, L1 <64us
        LnkSta: Speed 16GT/s (ok), Width x4 (ok)
        Capabilities: [100 v2] Advanced Error Reporting
                UESta:  DLP- SDES- TLP- FCP- CmpltTO- CmpltAbrt- UnxCmplt- RxOF- MalfTLP- ECRC- UnsupReq- ACSViol-
                CESta:  RxErr- BadTLP- BadDLLP- Rollover- Timeout- AdvNonFatalErr-
"""

SAMPLE_CHANGED = """
        LnkCap: Port #0, Speed 16GT/s, Width x4
        LnkSta: Speed 8GT/s (downgraded), Width x2 (downgraded)
                UESta:  DLP- SDES- TLP+ FCP-
                CESta:  RxErr+ BadTLP- BadDLLP-
"""


def test_extract_link_records_raw_values():
    assert extract_link_field(SAMPLE, "LnkCap", "Speed") == "16GT/s"
    assert extract_link_field(SAMPLE, "LnkCap", "Width") == "x4"
    assert extract_link_field(SAMPLE, "LnkSta", "Speed") == "16GT/s"
    assert extract_link_field(SAMPLE, "LnkSta", "Width") == "x4"


def test_extract_link_records_changed_values_for_diff():
    assert extract_link_field(SAMPLE_CHANGED, "LnkSta", "Speed") == "8GT/s"
    assert extract_link_field(SAMPLE_CHANGED, "LnkSta", "Width") == "x2"


def test_extract_aer_records_raw_flag_tokens():
    assert "TLP-" in extract_aer_field(SAMPLE, "UESta")
    assert "RxErr-" in extract_aer_field(SAMPLE, "CESta")
    assert "TLP+" in extract_aer_field(SAMPLE_CHANGED, "UESta")
    assert "RxErr+" in extract_aer_field(SAMPLE_CHANGED, "CESta")
