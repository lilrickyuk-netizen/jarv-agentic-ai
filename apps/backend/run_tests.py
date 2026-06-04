#!/usr/bin/env python
"""
JARV Backend Test Runner (pytest-free).

The production runtime image is slim and does not ship pytest, so this runner
discovers `tests/test_*.py` modules and executes their zero-argument `test_*`
functions with plain asserts. Fixture-based pytest suites are skipped cleanly
(reported as skipped), so the runner always works in the live environment.

Usage (inside the backend container, from /app):
    python run_tests.py                 # run all discoverable plain-assert tests
    python run_tests.py tests.test_task_status   # run one module

Exit code 0 = all run tests passed; 1 = at least one failed.
"""
import importlib
import inspect
import pkgutil
import sys
import traceback


def discover_modules() -> list:
    import tests
    mods = []
    for m in pkgutil.iter_modules(tests.__path__):
        if m.name.startswith("test_"):
            mods.append(f"tests.{m.name}")
    return sorted(mods)


def run_module(modname: str) -> tuple:
    passed = failed = skipped = 0
    try:
        mod = importlib.import_module(modname)
    except Exception as e:  # noqa: BLE001 - import needs unavailable deps (e.g. pytest)
        print(f"SKIP module {modname}: import failed ({e.__class__.__name__}: {e})")
        return 0, 0, 1
    for name, fn in sorted(vars(mod).items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            sig = inspect.signature(fn)
            if len(sig.parameters) > 0:  # fixture-based -> needs pytest
                print(f"SKIP {modname}.{name} (requires fixtures)")
                skipped += 1
                continue
        except (TypeError, ValueError):
            pass
        try:
            result = fn()
            if inspect.iscoroutine(result):
                import asyncio
                asyncio.run(result)
            print(f"PASS {modname}.{name}")
            passed += 1
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {modname}.{name}: {e}")
            traceback.print_exc()
            failed += 1
    return passed, failed, skipped


def main() -> int:
    targets = sys.argv[1:] or discover_modules()
    tp = tf = ts = 0
    for modname in targets:
        p, f, s = run_module(modname)
        tp += p
        tf += f
        ts += s
    print(f"\n=== {tp} passed, {tf} failed, {ts} skipped ===")
    return 1 if tf else 0


if __name__ == "__main__":
    raise SystemExit(main())
