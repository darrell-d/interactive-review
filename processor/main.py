"""Interactive file organizer step (ECS/Fargate).

Pennsieve runs this container as a paused workflow step. The files the run
selected (or the previous step's) are in INPUT_DIR; the person opens the web
app from the run page, renames and rearranges them, and saves. Nothing is
moved: the result is a manifest of what they did, as instructions for a later
step to execute. What happens next is this process's exit code:

  exit 0      the workflow continues, and everything under OUTPUT_DIR goes to
              the next step
  otherwise   the step, and the run, fail

How a session ends (see session.py):
  - the person saves the layout      -> write the manifest, exit 0
  - the person stops the workflow    -> log their notes, exit 1
  - End Session on the run page (the auth proxy POSTs /api/shutdown), or no
    request for IDLE_TIMEOUT_SECONDS -> exit 1: nothing was saved, so
    nothing goes on
  - the platform sends SIGTERM (cancel, teardown) -> exit 0, nothing written

The app never sees the workflow's task token. A sidecar the platform adds
holds it, waits for this container to exit, uploads OUTPUT_DIR and resumes
the workflow.

Nothing is written to OUTPUT_DIR until the person has saved. That sidecar
also uploads OUTPUT_DIR every few minutes while the session runs, and a
session that fails after such a checkpoint still hands it to the next steps.
A stop that had written anything there could be ignored.
"""

import logging
import os
import signal
import sys
import threading
import time

from werkzeug.serving import make_server

from processor.app import create_app
from processor.layout import input_files, write_manifest
from processor.session import CONTINUE, IDLE, STOP, TERMINATED, Session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
    force=True,
)
log = logging.getLogger("interactive-files")
# No access log. The first request of a session is "GET /?token=<session
# token>", and Werkzeug's request line would put that token in the step's log,
# which everyone with access to the run can read.
logging.getLogger("werkzeug").setLevel(logging.WARNING)

# How long the server keeps running after the session ends, so the response
# to the request that ended it ("Layout saved") reaches the browser. The
# request threads are daemons: they die with the process, mid-response or not.
RESPONSE_GRACE_SECONDS = 1


def _int_env(name, default):
    try:
        return int(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default


def get_config():
    return {
        "input_dir": os.environ.get("INPUT_DIR", ""),
        "output_dir": os.environ.get("OUTPUT_DIR", ""),
        "execution_run_id": os.environ.get("EXECUTION_RUN_ID", "unknown"),
        # Bind to localhost: the auth proxy shares this container's network
        # and is the only way in. It expects the app on port 8888.
        "bind_ip": os.environ.get("APP_IP", "127.0.0.1"),
        "port": _int_env("APP_PORT", 8888),
        # Close an abandoned session after this long without a request. The
        # platform has no idle timeout of its own for web apps, only a 12 hour
        # cap, and the task is billed while it runs.
        "idle_timeout": _int_env("IDLE_TIMEOUT_SECONDS", 3600),
    }


def watch_idle(session, idle_timeout, poll_seconds=5):
    """End the session once no request has come in for idle_timeout seconds."""
    while not session.ended.wait(poll_seconds):
        if session.idle_seconds() >= idle_timeout:
            session.end(IDLE)


def finish(cfg, session):
    """Write the outputs for how the session ended; returns the exit code."""
    outcome = session.outcome
    if outcome == TERMINATED:
        log.info("stopped by the platform; nothing written")
        return 0
    if outcome == STOP:
        # Only logged, never in OUTPUT_DIR (see the note at the top).
        log.error("the workflow was stopped from the app; failing the step. Notes: %s", session.notes or "(none)")
        return 1
    if outcome != CONTINUE:
        log.error("the session ended (%s) before a layout was saved; failing the step", outcome)
        return 1

    path = write_manifest(cfg["output_dir"], session.files, session.layout, session.operations, session.notes)
    changed = sum(1 for src, dest in session.layout.items() if src != dest)
    log.info("wrote %s", path)
    log.info(
        "%d operation(s), changing the path of %d of %d file(s); the workflow continues",
        len(session.operations), changed, len(session.files),
    )
    return 0


def main():
    cfg = get_config()
    if not cfg["input_dir"] or not cfg["output_dir"]:
        log.error("INPUT_DIR and OUTPUT_DIR must be set")
        return 2

    session = Session(input_files(cfg["input_dir"]))
    server = make_server(cfg["bind_ip"], cfg["port"], create_app(cfg, session), threaded=True)

    log.info("=" * 60)
    log.info("Interactive file organizer session")
    log.info("  executionRunId: %s", cfg["execution_run_id"])
    log.info("  input files:    %d in %s", len(session.files), cfg["input_dir"])
    log.info("  bind:           %s:%d", cfg["bind_ip"], cfg["port"])
    log.info("  idle timeout:   %ds", cfg["idle_timeout"])
    log.info("=" * 60)

    # Platform-initiated stop (a cancel, or teardown after the workflow moved
    # on): end without a decision.
    signal.signal(signal.SIGTERM, lambda _signum, _frame: session.end(TERMINATED))

    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=watch_idle, args=(session, cfg["idle_timeout"]), daemon=True).start()

    # Wake up every second so the SIGTERM handler gets to run.
    while not session.ended.wait(1):
        pass
    time.sleep(RESPONSE_GRACE_SECONDS)
    server.shutdown()
    return finish(cfg, session)


if __name__ == "__main__":
    sys.exit(main())
