"""The state of one session, shared by the web app's request threads and the
main thread that waits for the session to end.
"""

import threading
import time

# How a session ends. Only CONTINUE lets the workflow go on.
CONTINUE = "continue"      # the person saved the layout
STOP = "stop"              # the person stopped the workflow
CLOSED = "closed"          # End Session on the run page, before a save
IDLE = "idle"              # no request for IDLE_TIMEOUT_SECONDS
TERMINATED = "terminated"  # the platform stopped the task (cancel, teardown)


class Session:
    def __init__(self, files):
        self.files = files
        self.ended = threading.Event()
        self.outcome = None
        # What the person did, set with CONTINUE: the operations in order,
        # each input file's final path ({from: to}; layout.replay), and
        # their notes.
        self.operations = []
        self.layout = {}
        self.notes = ""
        self._lock = threading.Lock()
        self._last_request = time.monotonic()

    def touch(self):
        """Record a request from the person's browser."""
        self._last_request = time.monotonic()

    def idle_seconds(self):
        return time.monotonic() - self._last_request

    def end(self, outcome, layout=None, operations=None, notes=""):
        """End the session. The first call wins; returns whether this was it."""
        with self._lock:
            if self.outcome is not None:
                return False
            self.outcome = outcome
            self.layout = dict(layout or {})
            self.operations = list(operations or [])
            self.notes = notes
        self.ended.set()
        return True
