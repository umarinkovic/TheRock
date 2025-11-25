#!/usr/bin/env python3

import os
import platform
import subprocess
import json
from pathlib import Path
import re


SYSTEM = platform.system().lower()


def run_cmd(cmd: list[str]) -> str:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return out.strip()
    except Exception as e:
        return f"ERROR: {e}"


def run_rocm_bin(binary: str, *args: str) -> str:
    global THEROCK_BIN_DIR

    binary_name = binary + ".exe" if SYSTEM == "windows" else binary
    fullpath = Path(THEROCK_BIN_DIR) / binary_name

    return run_cmd([str(fullpath), *args])


def detect_gpu_linux():
    out = run_cmd(["lspci", "-nn"])
    gpus = []

    pattern = re.compile(
        r"^(?P<address>[0-9a-f:.]+) "
        r"(?P<class>.+?) \[.+?\]: "
        r"(?P<vendor>.+?) "
        r"\[(?P<id>[0-9a-f]{4}:[0-9a-f]{4})\]"
        r"(?: \(rev (?P<rev>[0-9a-f]+)\))?"
    )

    for line in out.splitlines():
        if (
            "VGA compatible controller" in line or "Display controller" in line
        ) and "[1002:" in line:
            match = pattern.match(line.strip())
            if match:
                gpus.append(
                    {
                        "address": match.group("address"),
                        "class": match.group("class"),
                        "vendor_model": match.group("vendor"),
                        "id": match.group("id"),
                        "rev": match.group("rev") or "",
                    }
                )

    return gpus


def detect_gpu_windows():
    cmd = (
        "Get-CimInstance Win32_VideoController | "
        "Where-Object { $_.Name -like '*AMD*' } | "
        "Select-Object -ExpandProperty Name"
    )
    out = run_cmd(["powershell", "-Command", cmd])
    return [line.strip() for line in out.splitlines() if line.strip()]


def detect_gpu_fallback():
    if SYSTEM == "linux":
        return detect_gpu_linux()
    elif SYSTEM == "windows":
        return detect_gpu_windows()
    else:
        raise Exception("Unsupported OS")


def parse_rocminfo(text: str) -> dict:
    lines = text.splitlines()

    system_info = {}
    for line in lines:
        if line.strip().startswith("HSA Agents"):
            break

        m = re.match(r"^(.*?):\s+(.*)$", line.strip())
        if m:
            system_info[m.group(1).strip()] = m.group(2).strip()

    parsed_system = {
        "runtime_version": system_info.get("Runtime Version"),
        "runtime_ext_version": system_info.get("Runtime Ext Version"),
        "xnack_enabled": system_info.get("XNACK enabled"),
        "dmabuf_support": system_info.get("DMAbuf Support"),
        "vmm_support": system_info.get("VMM Support"),
    }

    gpus = []
    current = None

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("Agent "):
            if current and current.get("Device Type") == "GPU":
                gpus.append(
                    {
                        "marketing_name": current.get("Marketing Name"),
                        "arch": current.get("Name"),
                        "uuid": current.get("Uuid"),
                        "chip_id": current.get("Chip ID"),
                        "compute_units": current.get("Compute Unit"),
                    }
                )
            current = {}
            continue

        if current is None:
            continue

        m = re.match(r"^(.*?):\s+(.*)$", stripped)
        if m and not m.group(1) in current:
            current[m.group(1).strip()] = m.group(2).strip()

    if current and current.get("Device Type") == "GPU":
        gpus.append(
            {
                "marketing_name": current.get("Marketing Name"),
                "arch": current.get("Name"),
                "uuid": current.get("Uuid"),
                "chip_id": current.get("Chip ID"),
                "compute_units": current.get("Compute Unit"),
            }
        )

    return {"system": parsed_system, "gpus": gpus}


def parse_hipcc(output: str) -> dict:
    result = {}

    hip_match = re.search(r"^HIP version: .+$", output, re.MULTILINE)
    if hip_match:
        result["HIP"] = hip_match.group(0).split(":", 1)[1].strip()

    clang_match = re.search(r"^AMD clang version .+$", output, re.MULTILINE)
    if clang_match:
        result["AMD Clang"] = clang_match.group(0).strip()

    return result


def detect_gpu_fallback():
    return detect_gpu_linux() if SYSTEM == "linux" else detect_gpu_windows()


def check_rocm():
    global THEROCK_BIN_DIR
    THEROCK_BIN_DIR = os.environ.get("THEROCK_BIN_DIR")

    if not THEROCK_BIN_DIR:
        print("[WARNING] THEROCK_BIN_DIR env variable not set.")
        return {"rocminfo": False, "hipcc": False}

    rocminfo_path = Path(THEROCK_BIN_DIR) / (
        "rocminfo.exe" if SYSTEM == "windows" else "rocminfo"
    )
    hipcc_path = Path(THEROCK_BIN_DIR) / (
        "hipcc.exe" if SYSTEM == "windows" else "hipcc"
    )

    rocminfo_exists = rocminfo_path.is_file()
    hipcc_exists = hipcc_path.is_file()

    if not rocminfo_exists:
        print(
            f"[WARNING] No rocminfo found at ${THEROCK_BIN_DIR}, falling back to baremetal detection."
        )
    if not hipcc_exists:
        print(f"[WARNING] hipcc not found in ${THEROCK_BIN_DIR}")
    return {"rocminfo": rocminfo_exists, "hipcc": hipcc_exists}


def main():

    rocm_availability = check_rocm()

    if rocm_availability["rocminfo"]:
        txt = run_rocm_bin("rocminfo")
        if txt:
            info = parse_rocminfo(txt)
        else:
            info = {"fallback_gpus": detect_gpu_fallback()}
    else:
        info = {"fallback_gpus": detect_gpu_fallback()}

    hipcc_v = (
        parse_hipcc(run_rocm_bin("hipcc", "--version"))
        if rocm_availability["hipcc"]
        else "Unknown"
    )

    result = {
        "os": SYSTEM,
        "rocm": {
            "rocminfo_available": rocm_availability["rocminfo"],
            "hipcc_available": rocm_availability["hipcc"],
            "hipcc_version": hipcc_v,
        },
        "info": info,
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
