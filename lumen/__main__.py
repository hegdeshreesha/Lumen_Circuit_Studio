"""Lumen Circuit Studio application entry point."""
import sys
import traceback


def _run() -> int:
    try:
        from lumen.app import main
    except ModuleNotFoundError as exc:
        missing = getattr(exc, "name", "") or "dependency"
        print(f"Missing Python dependency: {missing}", file=sys.stderr)
        print("Install project dependencies first:", file=sys.stderr)
        print("  python -m pip install -r requirements.txt", file=sys.stderr)
        return 2
    except Exception:
        traceback.print_exc()
        return 1

    return int(main())


if __name__ == "__main__":
    sys.exit(_run())
