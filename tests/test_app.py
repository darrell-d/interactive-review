"""The web app's routes, and what each way of ending a session does to the
step: its exit code and its outputs."""

import json
import os
import tempfile
import unittest

from processor.app import create_app
from processor.layout import input_files
from processor.main import finish, watch_idle
from processor.session import CLOSED, CONTINUE, IDLE, STOP, TERMINATED, Session


class AppTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = {
            "input_dir": os.path.join(tmp.name, "input"),
            "output_dir": os.path.join(tmp.name, "output"),
            "idle_timeout": 3600,
        }
        for path in ("raw/a.csv", "raw/b.csv"):
            full = os.path.join(self.cfg["input_dir"], path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(path)
        self.session = Session(input_files(self.cfg["input_dir"]))
        self.client = create_app(self.cfg, self.session).test_client()

    def save(self, operations=None, action="continue", notes=""):
        data = {"action": action, "notes": notes}
        if operations is not None:
            data["operations"] = json.dumps(operations)
        return self.client.post("/save", data=data)

    def outputs(self):
        if not os.path.isdir(self.cfg["output_dir"]):
            return []
        return [f["path"] for f in input_files(self.cfg["output_dir"])]

    def test_index_carries_the_files_for_the_page(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'"path": "raw/a.csv"', resp.data)
        self.assertIn(b'"path": "raw/b.csv"', resp.data)

    def test_index_drops_the_token_from_the_url(self):
        resp = self.client.get("/?token=abc")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["Location"], "/")

    def test_serves_an_input_file_but_nothing_outside_input_dir(self):
        resp = self.client.get("/files/raw/a.csv")
        self.assertEqual(resp.data, b"raw/a.csv")
        resp.close()
        self.assertEqual(self.client.get("/files/../output/x").status_code, 404)

    def test_saving_writes_the_manifest_and_exits_0(self):
        resp = self.save([{"op": "rename", "path": "raw", "name": "source"}], notes=" tidy ")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"1 operation in the manifest", resp.data)
        self.assertEqual(self.session.outcome, CONTINUE)
        self.assertEqual(finish(self.cfg, self.session), 0)
        self.assertEqual(self.outputs(), ["manifest/manifest.json"])
        with open(os.path.join(self.cfg["output_dir"], "manifest", "manifest.json")) as f:
            manifest = json.load(f)
        self.assertEqual(manifest["notes"], "tidy")
        self.assertEqual(manifest["operations"], [{"op": "rename", "kind": "folder", "path": "raw", "name": "source"}])
        self.assertEqual([f["to"] for f in manifest["files"]], ["source/a.csv", "source/b.csv"])

    def test_saving_with_nothing_done_is_a_manifest_with_no_operations(self):
        self.save([])
        self.assertEqual(finish(self.cfg, self.session), 0)
        with open(os.path.join(self.cfg["output_dir"], "manifest", "manifest.json")) as f:
            self.assertEqual(json.load(f)["operations"], [])

    def test_operations_that_can_not_be_done_are_refused(self):
        self.assertEqual(self.save([{"op": "rename", "path": "raw/a.csv", "name": "../a.csv"}]).status_code, 400)
        self.assertEqual(self.save([{"op": "rename", "path": "raw/a.csv", "name": "b.csv"}]).status_code, 400)
        self.assertEqual(self.client.post("/save", data={"action": "continue", "operations": "not json"}).status_code, 400)
        self.assertEqual(self.client.post("/save", data={"action": "continue", "operations": "{}"}).status_code, 400)
        self.assertEqual(self.save([], action="rename").status_code, 400)
        self.assertIsNone(self.session.outcome)

    def test_stop_fails_the_step_and_writes_nothing(self):
        # Anything in OUTPUT_DIR could reach the next steps through a
        # checkpoint, even from a failed session: a stop leaves it empty.
        self.save(action="stop", notes="wrong dataset")
        self.assertEqual(self.session.outcome, STOP)
        with self.assertLogs("interactive-files", level="ERROR") as logs:
            self.assertEqual(finish(self.cfg, self.session), 1)
        self.assertIn("wrong dataset", logs.output[0])
        self.assertEqual(self.outputs(), [])

    def test_end_session_before_a_save_fails_the_step(self):
        resp = self.client.post("/api/shutdown")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.session.outcome, CLOSED)
        self.assertEqual(finish(self.cfg, self.session), 1)
        self.assertEqual(self.outputs(), [])

    def test_end_session_after_a_save_keeps_the_save(self):
        self.save([{"op": "move", "path": "raw/a.csv", "to": ""}])
        self.client.post("/api/shutdown")
        self.assertEqual(self.session.outcome, CONTINUE)
        self.assertEqual(finish(self.cfg, self.session), 0)

    def test_a_second_save_is_refused(self):
        self.save(action="stop")
        resp = self.save([{"op": "move", "path": "raw/a.csv", "to": ""}])
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self.session.outcome, STOP)

    def test_an_idle_session_ends_and_fails_the_step(self):
        watch_idle(self.session, idle_timeout=0, poll_seconds=0.01)
        self.assertEqual(self.session.outcome, IDLE)
        self.assertEqual(finish(self.cfg, self.session), 1)

    def test_a_platform_stop_exits_0_and_writes_nothing(self):
        self.session.end(TERMINATED)
        self.assertEqual(finish(self.cfg, self.session), 0)
        self.assertEqual(self.outputs(), [])


if __name__ == "__main__":
    unittest.main()
