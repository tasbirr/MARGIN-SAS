#!/usr/bin/env python3
"""Environment checks for local setup."""
import importlib
import sys

MIN_PY = (3, 10)
MAX_PY = (3, 13)

REQUIRED = [
    "flask",
    "pandas",
    "numpy",
    "scipy",
    "werkzeug",
    "reportlab",
    "requests",
]


def main() -> int:
    version = sys.version_info
    if not (MIN_PY <= (version.major, version.minor) <= MAX_PY):
        print(
            "Python {major}.{minor} detected; please use 3.10-3.13.".format(
                major=version.major, minor=version.minor
            )
        )
        return 1

    missing = []
    for module in REQUIRED:
        try:
            importlib.import_module(module)
        except Exception:
            missing.append(module)

    if missing:
        print("Missing imports: {modules}".format(modules=", ".join(missing)))
        print("Run: python -m pip install -r requirements.txt")
        return 1

    print("Environment OK (Python {major}.{minor})".format(
        major=version.major, minor=version.minor
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
