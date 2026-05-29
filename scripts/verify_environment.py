"""Basic environment verification for Lumen Circuit Studio."""
from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import sys
from pathlib import Path


REQUIRED_MODULES = ("PyQt6", "jsonschema", "numpy")
OPTIONAL_MODULES = ("pytest",)
MIN_PYTHON = (3, 11)


def _module_present(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _check_python() -> tuple[bool, str]:
    ok = sys.version_info >= MIN_PYTHON
    want = ".".join(str(i) for i in MIN_PYTHON)
    got = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return ok, f"Python >= {want} (found {got})"


def _find_gspice() -> str:
    candidates = [
        Path(r"C:\EDA\GSPICE\build\Release\gspice.exe"),
        Path(r"C:\EDA\GSPICE\build\Debug\gspice.exe"),
        Path(r"C:\EDA\GSPICE\build\gspice.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return shutil.which("gspice") or ""


def _find_klayout() -> str:
    env = os.environ.get("LUMEN_KLAYOUT_EXE", "").strip() or os.environ.get("KLAYOUT_EXE", "").strip()
    if env and Path(env).exists():
        return env
    candidates = [
        Path(r"C:\EDA\LumenCircuitStudio\external\tools\KLayout\klayout_app.exe"),
        Path(r"C:\EDA\LumenCircuitStudio\external\tools\KLayout\klayout.exe"),
        Path(r"C:\Program Files\KLayout\klayout_app.exe"),
        Path(r"C:\Program Files\KLayout\klayout.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return shutil.which("klayout") or ""


def main() -> int:
    checks: list[tuple[bool, str]] = []
    checks.append(_check_python())

    for mod in REQUIRED_MODULES:
        checks.append((_module_present(mod), f"Required module: {mod}"))
    for mod in OPTIONAL_MODULES:
        checks.append((_module_present(mod), f"Optional module: {mod}"))

    gspice = _find_gspice()
    klayout = _find_klayout()
    checks.append((bool(gspice), "GSPICE executable"))
    checks.append((bool(klayout), "KLayout executable"))

    print("Lumen Environment Check")
    print("=" * 32)
    print(f"Platform: {platform.system()} {platform.release()}")
    print(f"Workspace: {Path.cwd()}")
    print("")
    for ok, label in checks:
        mark = "OK" if ok else "MISS"
        print(f"[{mark:4}] {label}")
    print("")
    print(f"GSPICE path : {gspice or '<not found>'}")
    print(f"KLayout path: {klayout or '<not found>'}")

    required_ok = all(ok for ok, label in checks if "Required module" in label or label.startswith("Python"))
    if not required_ok:
        print("")
        print("Install requirements with:")
        print("  python -m pip install -r requirements.txt")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
