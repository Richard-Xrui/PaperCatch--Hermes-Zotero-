import errno
import multiprocessing
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from json_store import (
    JsonStoreError,
    locked_update_json,
    read_json,
    write_json_atomic,
)


def _spawn_increment(path, iterations, start_event):
    start_event.wait()
    for _ in range(iterations):
        def increment(data):
            data["value"] += 1

        locked_update_json(path, {"value": 0}, increment)


class JsonStoreTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows replace retry is platform-specific")
    def test_windows_replace_retries_transient_access_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "data.json"
            path.write_text('{"value": 7}\n', encoding="utf-8")
            real_replace = os.replace
            calls = []

            def transient_replace(source, target):
                calls.append((source, target))
                if len(calls) == 1:
                    error = PermissionError(errno.EACCES, "temporarily busy")
                    error.winerror = 5
                    raise error
                return real_replace(source, target)

            with patch("json_store.os.replace", side_effect=transient_replace), patch(
                "json_store.time.sleep"
            ) as sleep:
                write_json_atomic(path, {"value": 8})

            self.assertEqual(2, len(calls))
            sleep.assert_called_once()
            self.assertEqual({"value": 8}, read_json(path, {}))

    def test_missing_file_returns_independent_default_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "missing.json"
            default = {"papers": [{"tags": []}]}

            first = read_json(path, default)
            second = read_json(path, default)
            first["papers"][0]["tags"].append("changed")

            self.assertEqual({"papers": [{"tags": []}]}, default)
            self.assertEqual({"papers": [{"tags": []}]}, second)
            self.assertFalse(path.exists())

    def test_malformed_existing_json_raises_path_specific_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "broken.json"
            original = b'{"papers": ['
            path.write_bytes(original)

            with self.assertRaises(JsonStoreError) as caught:
                read_json(path, {"papers": []})

            self.assertIn(str(path), str(caught.exception))
            self.assertEqual(original, path.read_bytes())

    def test_serialization_failure_preserves_original_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "data.json"
            original = b'{"value": 7}\n'
            path.write_bytes(original)

            with self.assertRaises(JsonStoreError) as caught:
                write_json_atomic(path, {"unsupported": object()})

            self.assertIn(str(path), str(caught.exception))
            self.assertEqual(original, path.read_bytes())
            self.assertEqual([path], list(root.iterdir()))

    def test_replace_failure_preserves_original_and_cleans_same_dir_temp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "data.json"
            original = b'{"value": 7}\n'
            path.write_bytes(original)

            with patch("json_store.os.replace", side_effect=OSError("replace failed")) as replace:
                with self.assertRaises(JsonStoreError) as caught:
                    write_json_atomic(path, {"value": 8})

            temp_path, target_path = replace.call_args.args
            self.assertEqual(root, Path(temp_path).parent)
            self.assertEqual(path, Path(target_path))
            self.assertIn(str(path), str(caught.exception))
            self.assertEqual(original, path.read_bytes())
            self.assertEqual([path], list(root.iterdir()))

    def test_locked_update_accepts_in_place_and_replacement_updaters(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "data.json"

            def append_first(data):
                data["items"].append("first")

            first = locked_update_json(path, {"items": []}, append_first)
            second = locked_update_json(
                path,
                {"items": []},
                lambda data: {"items": data["items"] + ["second"]},
            )

            self.assertEqual({"items": ["first"]}, first)
            self.assertEqual({"items": ["first", "second"]}, second)
            self.assertEqual(second, read_json(path, {}))

    def test_deep_equal_update_does_not_replace_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "data.json"
            original = b'{"value": 7, "nested": [1, 2]}\n'
            path.write_bytes(original)

            with patch("json_store.os.replace") as replace:
                result = locked_update_json(
                    path,
                    {},
                    lambda data: {"nested": list(data["nested"]), "value": data["value"]},
                )

            lock_path = Path(f"{path}.lock")
            replace.assert_not_called()
            self.assertEqual({"nested": [1, 2], "value": 7}, result)
            self.assertEqual(original, path.read_bytes())
            self.assertTrue(lock_path.exists())
            self.assertGreaterEqual(lock_path.stat().st_size, 1)

    def test_updater_failure_preserves_original_bytes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "data.json"
            original = b'{"value": 7}\n'
            path.write_bytes(original)

            def fail_after_mutation(data):
                data["value"] = 99
                raise RuntimeError("update failed")

            with self.assertRaisesRegex(RuntimeError, "update failed"):
                locked_update_json(path, {}, fail_after_mutation)

            self.assertEqual(original, path.read_bytes())

    def test_thread_contention_has_no_lost_updates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "counter.json"
            write_json_atomic(path, {"value": 0})
            worker_count = 6
            iterations = 20
            barrier = threading.Barrier(worker_count)
            failures = []

            def worker():
                try:
                    barrier.wait()
                    for _ in range(iterations):
                        def increment(data):
                            current = data["value"]
                            time.sleep(0.001)
                            data["value"] = current + 1

                        locked_update_json(path, {"value": 0}, increment)
                except BaseException as exc:
                    failures.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(worker_count)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)

            self.assertFalse([thread for thread in threads if thread.is_alive()])
            self.assertEqual([], failures)
            self.assertEqual(
                {"value": worker_count * iterations},
                read_json(path, {}),
            )

    def test_spawned_process_contention_has_no_lost_updates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "counter.json"
            write_json_atomic(path, {"value": 0})
            context = multiprocessing.get_context("spawn")
            start_event = context.Event()
            worker_count = 4
            iterations = 15
            processes = [
                context.Process(
                    target=_spawn_increment,
                    args=(str(path), iterations, start_event),
                )
                for _ in range(worker_count)
            ]

            for process in processes:
                process.start()
            start_event.set()
            for process in processes:
                process.join(timeout=30)

            alive = [process for process in processes if process.is_alive()]
            for process in alive:
                process.terminate()
                process.join(timeout=5)

            self.assertEqual([], alive)
            self.assertEqual([0] * worker_count, [process.exitcode for process in processes])
            self.assertEqual(
                {"value": worker_count * iterations},
                read_json(path, {}),
            )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    unittest.main()
