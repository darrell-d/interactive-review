"""The web app the reviewer sees: the list of input files, each one a link to
look at it, and a form to approve or reject them.

The auth proxy next to this container is the only way in, and it has checked
the reviewer's session token before a request gets here, so nothing below
authenticates.
"""

from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, url_for

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

    @app.post("/review")
    def review():
        action = request.form.get("action")
        approved = set(request.form.getlist("approved"))
        notes = request.form.get("notes", "").strip()
        if action not in (CONTINUE, STOP) or not approved <= {f["path"] for f in session.files}:
            abort(400)
        if action == CONTINUE and not approved:
            return page(error="Approve at least one file to continue, or stop the workflow."), 400
        # The first decision stands: a second tab, or a review after End
        # Session, is told how the session already ended.
        if not session.end(action, approved, notes):
            return render_template("ended.html", outcome=session.outcome), 409
        return render_template("ended.html", outcome=action, approved=len(approved))

    # The auth proxy calls this when someone clicks End Session on the run
    # page (the same call it makes to a Jupyter server). Without a submitted
    # review the step fails: see main.finish.
    @app.post("/api/shutdown")
    def shutdown():
        session.end(CLOSED)
        return jsonify(status="closing")

    return app
