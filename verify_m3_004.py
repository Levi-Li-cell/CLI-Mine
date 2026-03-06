"""Verification script for M3-004: code/artifact viewer."""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from artifacts import detect_language, export_artifact, preview_artifact


def ok(msg: str) -> None:
    print(f"   [PASS] {msg}")


def fail(msg: str, reason: str = "") -> None:
    print(f"   [FAIL] {msg}")
    if reason:
        print(f"          Reason: {reason}")
    raise SystemExit(1)


def main() -> None:
    print("=== M3-004 VERIFICATION: Code/Artifact Viewer ===\n")
    tmp = Path(tempfile.mkdtemp(prefix="m3_004_test_"))
    try:
        py_file = tmp / "sample.py"
        py_file.write_text("def hello(name):\n    # greeting\n    return 'hi ' + name\n", encoding="utf-8")

        img_file = tmp / "blob.bin"
        img_file.write_bytes(b"\x00\x01\x02binarypayload")

        print("1. Testing: language detection...")
        lang = detect_language(py_file)
        if lang != "python":
            fail("Detect python", f"lang={lang}")
        ok("Language detection works")

        print("\n2. Testing: code preview with highlighting...")
        preview = preview_artifact(py_file, max_chars=200)
        if preview.is_binary:
            fail("Code preview text mode", "preview marked binary")
        if preview.language != "python":
            fail("Code preview language", f"language={preview.language}")
        if "def" not in preview.preview or "return" not in preview.preview:
            fail("Code preview content", "missing expected tokens")
        ok("Code preview and highlighting path works")

        print("\n3. Testing: binary artifact preview...")
        binary_preview = preview_artifact(img_file)
        if not binary_preview.is_binary:
            fail("Binary detection", "expected binary artifact")
        if "binary artifact" not in binary_preview.preview:
            fail("Binary preview message", binary_preview.preview)
        ok("Binary preview path works")

        print("\n4. Testing: artifact export/download support...")
        export_path = tmp / "exports" / "sample_copy.py"
        out = export_artifact(py_file, export_path)
        if not out.exists():
            fail("Export file existence")
        if out.read_text(encoding="utf-8") != py_file.read_text(encoding="utf-8"):
            fail("Export file content", "copied content mismatch")
        ok("Artifact export works")

        print("\n=== M3-004 VERIFICATION PASSED ===")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
