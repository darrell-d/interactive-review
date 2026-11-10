"""What the review reads and writes: the files under INPUT_DIR, and the two
outputs declared in app.yml (OUTPUT_DIR/approved/, OUTPUT_DIR/review/).
"""

import json
import os
import shutil
from datetime import datetime, timezone

# The outputs declared in app.yml.
APPROVED = "approved"
REVIEW = "review"


def input_files(input_dir):
    """Every file below INPUT_DIR: [{"path", "size"}], path relative to it."""
    files = []
    for dirpath, _, filenames in os.walk(input_dir, followlinks=True):
        for name in filenames:
            full = os.path.join(dirpath, name)
            files.append({"path": os.path.relpath(full, input_dir), "size": os.path.getsize(full)})
    return sorted(files, key=lambda f: f["path"])


def write_review(output_dir, files, approved, notes):
    """Write OUTPUT_DIR/review/review.json: the decision for every file."""
    review = {
        "at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
        "files": [
            {"path": f["path"], "size": f["size"], "decision": "approved" if f["path"] in approved else "rejected"}
            for f in files
        ],
    }
    folder = os.path.join(output_dir, REVIEW)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "review.json")
    with open(path, "w") as out:
        json.dump(review, out, indent=2)
    return path


def copy_approved(input_dir, output_dir, approved):
    """Copy the approved files to OUTPUT_DIR/approved/, keeping their paths,
    so the next step finds them where the previous step put them."""
    for path in sorted(approved):
        dest = os.path.join(output_dir, APPROVED, path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(os.path.join(input_dir, path), dest)
