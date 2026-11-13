"""The web app the person sees: the input files as a folder tree they can
rename and rearrange, and a form that sends the new layout back.

The page keeps the layout in the browser until it is saved, and records each
thing the person does as an operation. The server replays those operations
on the input files (layout.replay), which both checks them and gives the
final layout, and ends the session.

The auth proxy next to this container is the only way in, and it has checked
the person's session token before a request gets here, so nothing below
authenticates.
"""

import json

from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, url_for

from processor.layout import replay
from processor.session import CLOSED, CONTINUE, STOP


def create_app(cfg, session):
    app = Flask(__name__)

    def page(error=""):
        return render_template(
            "index.html",
            files=session.files,
            idle_minutes=cfg["idle_timeout"] // 60,
            error=error,
        )

    @app.before_request
    def seen():
        session.touch()

    @app.get("/")
    def index():
        # The run page opens the session with its token in the URL. The auth
        # proxy has moved it into a cookie by now, so take it out of the
        # address bar.
        if "token" in request.args:
            return redirect(url_for("index"))
        if session.outcome is not None:
            return render_template("ended.html", outcome=session.outcome), 410
        return page()

    # An input file, to look at in the browser. Named /files/ like Jupyter's,
    # so the platform's limits on that path (no large downloads through its
    # interactive gateway) apply here too.
    @app.get("/files/<path:path>")
    def file(path):
        return send_from_directory(cfg["input_dir"], path)

    @app.post("/save")
    def save():
        action = request.form.get("action")
        notes = request.form.get("notes", "").strip()
        if action not in (CONTINUE, STOP):
            abort(400)
        layout, operations = {}, []
        if action == CONTINUE:
            try:
                sent = json.loads(request.form.get("operations") or "[]")
            except ValueError:
                abort(400)
            if not isinstance(sent, list):
                abort(400)
            # The page only records operations that hold, so this fails only
            # for a request that didn't come from it.
            layout, operations, why = replay(session.files, sent)
            if layout is None:
                return page(error=f"That can't be saved: {why}."), 400
        # The first decision stands: a second tab, or a save after End
        # Session, is told how the session already ended.
        if not session.end(action, layout, operations, notes):
            return render_template("ended.html", outcome=session.outcome), 409
        return render_template("ended.html", outcome=action, operations=len(operations))

    # The auth proxy calls this when someone clicks End Session on the run
    # page (the same call it makes to a Jupyter server). Without a saved
    # layout the step fails: see main.finish.
    @app.post("/api/shutdown")
    def shutdown():
        session.end(CLOSED)
        return jsonify(status="closing")

    return app
