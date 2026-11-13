"""Regression tests for successful extractors returning unusable bounding boxes."""
import io
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools import verify_layout


class EmptyExtractorOutputTests(unittest.TestCase):
    def test_output_without_pages_is_an_extraction_error(self):
        for output in ("", "not bounding-box output", "<html><body></body></html>"):
            with self.subTest(output=output), patch.object(
                verify_layout, "find_pdftotext", return_value="/mock/pdftotext"
            ), patch.object(
                verify_layout.subprocess, "run",
                return_value=subprocess.CompletedProcess([], 0, stdout=output),
            ):
                with self.assertRaisesRegex(RuntimeError, "no.*page|page.*not|bounding boxes"):
                    verify_layout.parse_pdf(Path("example.pdf"))

    def test_unusable_output_exits_skipped_without_claiming_clean(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(verify_layout, "find_pdftotext", return_value="/mock/pdftotext"), patch.object(
            verify_layout.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 0, stdout="not bounding-box output"),
        ), patch("sys.argv", ["verify_layout.py", __file__]), redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(verify_layout.main(), 2)
        self.assertIn("skipped:", stderr.getvalue())
        self.assertNotIn("layout: clean", stdout.getvalue())

    def test_valid_blank_page_is_a_document_problem(self):
        with patch.object(verify_layout, "find_pdftotext", return_value="/mock/pdftotext"), patch.object(
            verify_layout.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 0, stdout='<page width="595" height="842"></page>'),
        ):
            pages = verify_layout.parse_pdf(Path("example.pdf"))
        self.assertEqual(len(pages), 1)
        with redirect_stdout(io.StringIO()):
            self.assertIn("p1 contains no text", verify_layout.report(Path("example.pdf"), pages))


if __name__ == "__main__":
    unittest.main()
