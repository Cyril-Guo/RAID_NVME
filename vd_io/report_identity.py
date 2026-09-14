"""Match report records by host, run key and test function, not by suite count."""
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def labels(result):
    return {x.get("name"): x.get("value") for x in result.get("labels", [])}


def set_label(result, name, value):
    result["labels"] = [x for x in result.get("labels", []) if x.get("name") != name]
    result["labels"].append({"name": name, "value": value})


def host(result):
    value = labels(result).get("host")
    if value:
        return value
    match = re.search(r"(?:physical:|Physical )(\d+\.\d+\.\d+\.\d+)",
                      str(result.get("fullName", "")) + " " + str(result.get("name", "")))
    return match[1] if match else ""


def run_from_class(classname):
    value = str(classname).rsplit(".", 1)[-1]
    return re.sub(r"^test_(?:ci|smoke)_\d+_", "", value)


def run_key(result):
    values = labels(result)
    if values.get("run_key"):
        return values["run_key"]
    for value in (values.get("package", ""), values.get("suite", ""), result.get("fullName", "")):
        match = re.search(r"(?:^|[.:/])([a-z][a-z0-9_]*?__\d+)(?:$|[.:/#])", str(value))
        if match:
            return match[1]
        match = re.search(r"test_(?:ci|smoke)_\d+_([a-z0-9_]+)", str(value))
        if match:
            return match[1]
    return ""


def function_name(result):
    fullname = str(result.get("fullName", ""))
    if "#" in fullname:
        return fullname.rsplit("#", 1)[-1]
    name = re.sub(r"^\[[^]]+\]\s*", "", str(result.get("name", "")))
    return labels(result).get("pytest_record") or (name if name.startswith("test_") or name in ("unknown", "internal") else "")


def case_run_key(case):
    if case.get("name") in ("unknown", "internal"):
        return ""
    properties = {p.get("name"): p.get("value") for p in case.findall("properties/property")}
    return properties.get("run_key") or run_from_class(case.get("classname", ""))


def native_case_exists(allure_dir, case, node):
    wanted_run = case_run_key(case)
    wanted_function = case.get("name", "")
    for path in Path(allure_dir).glob("*-result.json"):
        result = read_json(path)
        if not result or host(result) != node or function_name(result) != wanted_function:
            continue
        actual_run = run_key(result)
        if actual_run and wanted_run and actual_run != wanted_run:
            continue
        detail = case.find("failure")
        status = "failed"
        if detail is None:
            detail = case.find("error")
            status = "broken"
        if detail is not None and result.get("status") not in ("failed", "broken"):
            result.update(status=status, statusDetails={"message": detail.get("message", status),
                          "trace": detail.text or detail.get("message", status)})
            save_json(path, result)
        return True
    return False


def all_attachments(result):
    output = list(result.get("attachments") or [])
    for step in result.get("steps") or []:
        output.extend(all_attachments(step))
    return output


def merge_record(destination, source):
    destination.setdefault("attachments", []).extend(all_attachments(source))
    if source.get("status") in ("failed", "broken"):
        original = destination.get("statusDetails") or {}
        extra = source.get("statusDetails") or {}
        if destination.get("status") not in ("failed", "broken"):
            destination["status"] = source["status"]
        destination["statusDetails"] = {
            "message": original.get("message") or extra.get("message", ""),
            "trace": "\n".join(dict.fromkeys(x for x in (
                original.get("trace"), extra.get("message"), extra.get("trace")) if x)),
        }


def normalize_results(allure_dir):
    root = Path(allure_dir)
    records = [(p, read_json(p)) for p in root.glob("*-result.json")]
    records = [(p, r) for p, r in records if r is not None]
    records.sort(key=lambda pair: labels(pair[1]).get("parentSuite") != "测试日志")
    concrete_hosts = {host(r) for _, r in records if function_name(r).startswith("test_") or run_key(r)}
    seen = {}
    removed = 0
    for path, result in records:
        values = labels(result)
        if values.get("framework") != "pytest":
            continue
        function = function_name(result)
        key = (host(result), run_key(result), function)
        if function == "unknown" and result.get("status") == "passed" and host(result) in concrete_hosts:
            recipients = [r for _, r in records if host(r) == host(result) and function_name(r).startswith("test_")]
            for recipient in recipients:
                recipient.setdefault("attachments", []).extend(all_attachments(result))
            path.unlink()  # Derived placeholder only; real errors are never removed here.
            removed += 1
            continue
        if function and function not in ("unknown", "internal") and key in seen:
            kept_path, kept = seen[key]
            merge_record(kept, result)
            save_json(kept_path, kept)
            path.unlink()
            removed += 1
            continue
        if function:
            seen[key] = (path, result)
        set_label(result, "parentSuite", "测试日志")
        if host(result):
            set_label(result, "host", host(result))
        if function in ("unknown", "internal"):
            set_label(result, "pytest_record", function)
            set_label(result, "suite", "执行诊断")
            result["name"] = f"[Physical {host(result) or 'unknown'}] pytest 执行异常"
        else:
            suite = run_key(result) or values.get("suite") or "测试用例"
            set_label(result, "suite", suite if suite != "pytest" else "测试用例")
            if run_key(result):
                set_label(result, "run_key", run_key(result))
        result["labels"] = [x for x in result["labels"] if not (x.get("name") == "subSuite" and x.get("value") == "pytest")]
        save_json(path, result)
    # Persist evidence moved from placeholders even when their recipient was processed first.
    for path, result in records:
        if path.exists():
            save_json(path, result)
    return removed


def discard_junit_placeholders(allure_dir):
    hosts = {host(r) for p in Path(allure_dir).glob("*-result.json")
             if (r := read_json(p)) and (run_key(r) or function_name(r).startswith("test_"))}
    for path in Path(".").glob("report_*.xml"):
        node = path.stem.removeprefix("report_").removesuffix("_physical")
        if node not in hosts:
            continue
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            continue
        changed = False
        for suite in root.iter("testsuite"):
            for case in list(suite.findall("testcase")):
                if case.get("name") == "unknown" and case.find("failure") is None and case.find("error") is None:
                    suite.remove(case)
                    changed = True
        if changed:
            for parent in [*root.findall(".//testsuite"), root]:
                cases = list(parent.iter("testcase"))
                for key, tag in (("tests", None), ("failures", "failure"), ("errors", "error"), ("skipped", "skipped")):
                    parent.set(key, str(sum(tag is None or c.find(tag) is not None for c in cases)))
            ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
