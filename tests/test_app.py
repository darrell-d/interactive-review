"""The web app's routes, and what each way of ending a session does to the
step: its exit code and its outputs."""

import json
import os
import tempfile
import unittest

from processor.app import create_app
from processor.main import finish, watch_idle
from processor.review import input_files
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
        for path in ("sub-01/volumes.csv", "sub-02/volumes.csv"):
            full = os.path.join(self.cfg["input_dir"], path)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w") as f:
                f.write(path)
        self.session = Session(input_files(self.cfg["input_dir"]))
        self.client = create_app(self.cfg, self.session).test_client()

    def post(self, path, data=None):
        return self.client.post(path, data=data)

    def outputs(self):
        if not os.path.isdir(self.cfg["output_dir"]):
            return []
        return [f["path"] for f in input_files(self.cfg["output_dir"])]

    def test_index_lists_the_files(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"sub-01/volumes.csv", resp.data)
        self.assertIn(b"sub-02/volumes.csv", resp.data)

    def test_index_drops_the_token_from_the_url(self):
        resp = self.client.get("/?token=abc")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["Location"], "/")

    def test_serves_an_input_file_but_nothing_outside_input_dir(self):
        resp = self.client.get("/files/sub-01/volumes.csv")
        self.assertEqual(resp.data, b"sub-01/volumes.csv")
        resp.close()
        self.assertEqual(self.client.get("/files/../output/x").status_code, 404)

    def test_continue_copies_the_approved_files_and_exits_0(self):
        resp = self.post("/review", {"action": "continue", "approved": ["sub-01/volumes.csv"], "notes": " ok "})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.session.outcome, CONTINUE)
        self.assertEqual(finish(self.cfg, self.session), 0)
        self.assertEqual(self.outputs(), ["approved/sub-01/volumes.csv", "review/review.json"])
        with open(os.path.join(self.cfg["output_dir"], "review", "review.json")) as f:
            self.assertEqual(json.load(f)["notes"], "ok")

    def test_continue_with_nothing_approved_is_refused(self):
        resp = self.post("/review", {"action": "continue"})
        self.assertEqual(resp.status_code, 400)
        self.assertIsNone(self.session.outcome)

    def test_an_unknown_file_or_action_is_refused(self):
        self.assertEqual(self.post("/review", {"action": "continue", "approved": ["../etc/passwd"]}).status_code, 400)
        self.assertEqual(self.post("/review", {"action": "approve", "approved": ["sub-01/volumes.csv"]}).status_code, 400)
        self.assertIsNone(self.session.outcome)

    def test_stop_fails_the_step_and_writes_nothing(self):
        # Anything in OUTPUT_DIR could reach the next steps through a
        # checkpoint, even from a failed session: a stop leaves it empty.
        self.post("/review", {"action": "stop", "approved": ["sub-01/volumes.csv"], "notes": "bad registration"})
        self.assertEqual(self.session.outcome, STOP)
        with self.assertLogs("interactive-review", level="ERROR") as logs:
            self.assertEqual(finish(self.cfg, self.session), 1)
        self.assertIn("bad registration", logs.output[0])
        self.assertEqual(self.outputs(), [])

    def test_end_session_before_a_review_fails_the_step(self):
        resp = self.post("/api/shutdown")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.session.outcome, CLOSED)
        self.assertEqual(finish(self.cfg, self.session), 1)
        self.assertEqual(self.outputs(), [])

    def test_end_session_after_a_review_keeps_the_review(self):
        self.post("/review", {"action": "continue", "approved": ["sub-02/volumes.csv"]})
        self.post("/api/shutdown")
        self.assertEqual(self.session.outcome, CONTINUE)
        self.assertEqual(finish(self.cfg, self.session), 0)

    def test_a_second_review_is_refused(self):
        self.post("/review", {"action": "stop"})
        resp = self.post("/review", {"action": "continue", "approved": ["sub-01/volumes.csv"]})
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
