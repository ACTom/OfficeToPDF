"""Tests for converter output-file discovery.

Runnable two ways (no external deps required):
    python3 tests/test_converter.py     # standalone runner
    pytest tests/test_converter.py      # if pytest is installed
"""
import os
import tempfile

# config.py reads LOG_DIR/DATA_DIR at import time and creates them, so point
# them at throwaway dirs before importing the app package.
os.environ.setdefault("LOG_DIR", tempfile.mkdtemp(prefix="o2p_log_"))
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="o2p_data_"))

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.converter import _find_output_file, _target_extension, safe_filename  # noqa: E402


def test_target_extension_defaults_to_pdf():
    assert _target_extension(None) == "pdf"
    assert _target_extension("") == "pdf"
    assert _target_extension("pdf") == "pdf"
    assert _target_extension("pdf:writer_pdf_Export") == "pdf"


def test_target_extension_parses_non_pdf():
    assert _target_extension("html:XHTML Calc File") == "html"
    assert _target_extension("xhtml:XHTML Calc File") == "xhtml"
    assert _target_extension("  HTML : foo ") == "html"


def test_find_output_html():
    """The bug: converting to html produced report.html but the finder only
    looked for .pdf and reported 'Output file not created'."""
    with tempfile.TemporaryDirectory() as out_dir:
        with open(os.path.join(out_dir, "report.html"), "w") as f:
            f.write("<html></html>")
        found = _find_output_file("/somewhere/report.xlsx", out_dir, "html")
        assert found == os.path.join(out_dir, "report.html")


def test_find_output_pdf_still_works():
    with tempfile.TemporaryDirectory() as out_dir:
        with open(os.path.join(out_dir, "report.pdf"), "wb") as f:
            f.write(b"%PDF-1.4")
        found = _find_output_file("/somewhere/report.docx", out_dir, "pdf")
        assert found == os.path.join(out_dir, "report.pdf")


def test_find_output_missing_returns_none():
    with tempfile.TemporaryDirectory() as out_dir:
        assert _find_output_file("/somewhere/report.xlsx", out_dir, "html") is None


def test_safe_filename_keeps_plain_names():
    assert safe_filename("report.docx") == "report.docx"
    assert safe_filename("my file (1).xlsx") == "my file (1).xlsx"


def test_safe_filename_strips_traversal():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("/etc/shadow") == "shadow"
    assert safe_filename("..\\..\\windows\\system32\\x.dll") == "x.dll"
    assert safe_filename("sub/dir/report.pdf") == "report.pdf"


def test_safe_filename_handles_empty_and_dots():
    assert safe_filename(None) == "upload"
    assert safe_filename("") == "upload"
    assert safe_filename("..") == "upload"
    assert safe_filename(".") == "upload"
    assert safe_filename("   ") == "upload"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {e!r}")
    if failures:
        print(f"\n{failures} test(s) failed")
        sys.exit(1)
    print("\nAll tests passed")
