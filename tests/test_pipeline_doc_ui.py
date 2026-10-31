"""파이프라인 설명 페이지 — 테마 전달·iframe 표시 규칙·저장된 문서."""

from __future__ import annotations

import unittest

from app.ui.pipeline_doc import DOCUMENT, prepare_for_iframe, with_theme

_DOC = """<!doctype html>
<html lang="ko">
<head><title>t</title></head>
<body>
<nav class="rail"><a href="#p-a">A</a></nav>
<article class="prompt" id="p-a">
  <pre class="raw"><code># A 시스템 프롬프트
지시 1
</code></pre>
</article>
</body>
</html>
"""


class WithThemeTests(unittest.TestCase):
    def test_dark_theme_is_written_to_the_root_element(self) -> None:
        self.assertIn('<html lang="ko" data-theme="dark">', with_theme(_DOC, "dark"))

    def test_light_theme_is_written_to_the_root_element(self) -> None:
        self.assertIn('<html lang="ko" data-theme="light">', with_theme(_DOC, "light"))

    def test_unknown_theme_leaves_the_document_alone(self) -> None:
        self.assertEqual(with_theme(_DOC, None), _DOC)
        self.assertEqual(with_theme(_DOC, "sepia"), _DOC)

    def test_only_the_root_tag_changes(self) -> None:
        themed = with_theme(_DOC, "dark")
        self.assertEqual(themed.count("<html"), 1)
        self.assertIn("지시 1", themed)


class PrepareForIframeTests(unittest.TestCase):
    def test_rules_are_inserted_once_before_head_closes(self) -> None:
        embedded = prepare_for_iframe(_DOC)

        self.assertEqual(embedded.count("</head>"), 1)
        self.assertEqual(embedded.count("<style>"), 1)
        self.assertLess(embedded.index("<style>"), embedded.index("</head>"))
        self.assertIn(".rail { display: block;", embedded)

    def test_anchor_script_is_inserted_once_before_body_closes(self) -> None:
        """목차의 `#id` 링크가 iframe 밖(앱 페이지)으로 새지 않게 잡는 스크립트."""
        embedded = prepare_for_iframe(_DOC)

        self.assertEqual(embedded.count("</body>"), 1)
        self.assertEqual(embedded.count("<script>"), 1)
        self.assertLess(embedded.index("<script>"), embedded.index("</body>"))
        self.assertIn("event.preventDefault()", embedded)
        self.assertIn("scroller.scrollTo(", embedded)

    def test_document_without_head_or_body_is_left_alone(self) -> None:
        self.assertEqual(prepare_for_iframe("<p>본문만</p>"), "<p>본문만</p>")

    def test_content_is_preserved(self) -> None:
        self.assertIn("지시 1", prepare_for_iframe(_DOC))


class StoredDocumentTests(unittest.TestCase):
    """저장소에 담긴 문서가 페이지가 기대하는 모양인지."""

    def setUp(self) -> None:
        self.assertTrue(DOCUMENT.is_file(), f"설명 문서가 없습니다: {DOCUMENT}")
        self.text = DOCUMENT.read_text(encoding="utf-8")

    def test_is_a_full_html_document(self) -> None:
        """테마 전달(<html>)과 표시 규칙 삽입(</head>·</body>)이 기대는 자리가 있어야 한다."""
        self.assertRegex(self.text, r"<html\b")
        self.assertIn("</head>", self.text)
        self.assertIn("</body>", self.text)

    def test_covers_both_pipelines_with_prompt_originals(self) -> None:
        self.assertIn('id="part-timeline"', self.text)
        self.assertIn('id="part-um"', self.text)
        self.assertIn('<pre class="raw">', self.text)


if __name__ == "__main__":
    unittest.main()
