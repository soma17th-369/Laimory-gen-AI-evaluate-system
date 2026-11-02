"""json 저장 — 쓰는 도중에도 읽는 쪽은 완전한 파일만 본다."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from app.storage import store


class StoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)


class SaveJsonTests(StoreTestCase):
    def test_creates_parent_folders_and_keeps_korean(self) -> None:
        path = self.root / "a" / "b.json"

        store.save_json(path, {"이름": "값"})

        self.assertIn("값", path.read_text(encoding="utf-8"))

    def test_leaves_no_temporary_file(self) -> None:
        path = self.root / "b.json"

        store.save_json(path, {"a": 1})
        store.save_json(path, {"a": 2})

        self.assertEqual([item.name for item in self.root.iterdir()], ["b.json"])

    def test_failed_replace_keeps_the_old_file(self) -> None:
        path = self.root / "b.json"
        store.save_json(path, {"a": 1})

        with mock.patch.object(store.os, "replace", side_effect=OSError("막힘")):
            with self.assertRaises(OSError):
                store.save_json(path, {"a": 2})

        self.assertEqual(store.load_json(path), {"a": 1})
        self.assertEqual([item.name for item in self.root.iterdir()], ["b.json"])

    def test_value_that_cannot_be_serialized_keeps_the_old_file(self) -> None:
        path = self.root / "b.json"
        store.save_json(path, {"a": 1})

        with self.assertRaises(TypeError):
            store.save_json(path, {"a": object()})

        self.assertEqual(store.load_json(path), {"a": 1})

    def test_replace_is_retried_while_another_process_holds_the_file(self) -> None:
        path = self.root / "b.json"
        real_replace = store.os.replace
        answers = [PermissionError("사용 중"), PermissionError("사용 중")]

        def replace(source, target):
            if answers:
                raise answers.pop(0)
            real_replace(source, target)

        with mock.patch.object(store.os, "replace", replace), mock.patch.object(store.time, "sleep"):
            store.save_json(path, {"a": 1})

        self.assertEqual(store.load_json(path), {"a": 1})

    def test_readers_never_see_a_partial_file(self) -> None:
        path = self.root / "b.json"
        store.save_json(path, list(range(2000)))
        stop = threading.Event()
        problems: list[object] = []

        def read() -> None:
            while not stop.is_set():
                data = store.read_json(path)
                if data is None or len(data) != 2000:
                    problems.append(data)

        reader = threading.Thread(target=read)
        reader.start()
        try:
            for turn in range(100):
                store.save_json(path, [turn] * 2000)
        finally:
            stop.set()
            reader.join()

        self.assertEqual(problems, [])


class ReadJsonTests(StoreTestCase):
    def test_missing_file_is_none(self) -> None:
        self.assertIsNone(store.read_json(self.root / "없음.json"))

    def test_broken_file_raises(self) -> None:
        path = self.root / "b.json"
        path.write_text("{ 끊긴", encoding="utf-8")

        with self.assertRaises(store.CorruptJson):
            store.read_json(path)

    def test_non_utf8_file_raises(self) -> None:
        path = self.root / "b.json"
        path.write_bytes(b"\xff\xfe\x00")

        with self.assertRaises(store.CorruptJson):
            store.read_json(path)

    def test_load_json_still_reads_broken_file_as_none(self) -> None:
        path = self.root / "b.json"
        path.write_text("{ 끊긴", encoding="utf-8")

        self.assertIsNone(store.load_json(path))

    def test_saved_value_round_trips(self) -> None:
        path = self.root / "b.json"
        store.save_json(path, {"a": [1, "둘"]})

        self.assertEqual(store.read_json(path), json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
