"""The layout the app reads and writes: the files under INPUT_DIR, the
operations the person did to them in the page, and the manifest that lists
those as instructions (OUTPUT_DIR/manifest/manifest.json, the output declared
in app.yml).

Nothing is moved here. The manifest is the result: a later step executes its
operations where the files really live.
"""

import json
import os
import posixpath
from datetime import datetime, timezone

# The output declared in app.yml.
MANIFEST = "manifest"


def input_files(input_dir):
    """Every file below INPUT_DIR: [{"path", "size"}], path relative to it."""
    files = []
    for dirpath, _, filenames in os.walk(input_dir, followlinks=True):
        for name in filenames:
            full = os.path.join(dirpath, name)
            path = os.path.relpath(full, input_dir).replace(os.sep, "/")
            files.append({"path": path, "size": os.path.getsize(full)})
    return sorted(files, key=lambda f: f["path"])


def _parent(path):
    return posixpath.dirname(path)


def _join(folder, name):
    return f"{folder}/{name}" if folder else name


def _bad_name(name):
    """Why a file or folder name can't be used, or "" when it can."""
    if not isinstance(name, str) or not name.strip():
        return "is empty"
    if name in (".", "..") or "/" in name or "\\" in name:
        return "isn't a plain name"
    return ""


class _Tree:
    """The files and folders as they stand while the operations are replayed:
    each input file's current path, and every folder, empty ones included."""

    def __init__(self, files):
        self.files = {f["path"]: f["path"] for f in files}  # original -> current
        self.folders = set()
        for path in self.files:
            parts = path.split("/")[:-1]
            self.folders.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))

    def kind(self, path):
        """"file", "folder", or "" when nothing is at the path."""
        if path in self.files.values():
            return "file"
        return "folder" if path in self.folders else ""

    def relocate(self, old, new):
        """Put the file or folder at old, and all that's in it, at new."""
        moved = lambda p: new if p == old else new + p[len(old):] if p.startswith(old + "/") else p
        self.files = {src: moved(cur) for src, cur in self.files.items()}
        self.folders = {moved(f) for f in self.folders}


def replay(files, operations):
    """Apply the operations the page recorded, in order, to the input files.

    Returns (layout, operations, "") or (None, None, why not): layout is
    {original path: final path} for every input file, and operations the same
    list with each one's "kind" ("file" or "folder") filled in from what was
    at its path. Each operation's paths are as they stand after the ones
    before it:

      {"op": "create_folder", "path": "archive"}
      {"op": "rename", "path": "raw", "name": "source"}
      {"op": "move", "path": "notes.txt", "to": "archive"}   ("" is the top)
    """
    tree = _Tree(files)
    done = []
    for n, op in enumerate(operations, start=1):
        if not isinstance(op, dict):
            return None, None, f"operation {n} isn't an operation"
        what, path = op.get("op"), op.get("path")
        if not isinstance(path, str) or not path:
            return None, None, f"operation {n} has no path"

        if what == "create_folder":
            why = next((w for w in map(_bad_name, path.split("/")) if w), "")
            if why:
                return None, None, f"operation {n}: the folder's path {why}"
            if tree.kind(path):
                return None, None, f"operation {n}: {path!r} already exists"
            if _parent(path) and tree.kind(_parent(path)) != "folder":
                return None, None, f"operation {n}: {_parent(path)!r} isn't a folder"
            tree.folders.add(path)
            done.append({"op": what, "path": path})
            continue

        kind = tree.kind(path)
        if not kind:
            return None, None, f"operation {n}: nothing is at {path!r}"
        if what == "rename":
            name = op.get("name")
            why = _bad_name(name)
            if why:
                return None, None, f"operation {n}: the new name {why}"
            new = _join(_parent(path), name)
            record = {"op": what, "kind": kind, "path": path, "name": name}
        elif what == "move":
            to = op.get("to")
            if not isinstance(to, str) or (to and tree.kind(to) != "folder"):
                return None, None, f"operation {n}: {to!r} isn't a folder"
            if kind == "folder" and (to == path or to.startswith(path + "/")):
                return None, None, f"operation {n}: a folder can't go inside itself"
            new = _join(to, posixpath.basename(path))
            record = {"op": what, "kind": kind, "path": path, "to": to}
        else:
            return None, None, f"operation {n}: {what!r} isn't something this app does"
        if new != path:
            if tree.kind(new):
                return None, None, f"operation {n}: {new!r} already exists"
            tree.relocate(path, new)
        done.append(record)
    return tree.files, done, ""


def write_manifest(output_dir, files, layout, operations, notes):
    """Write OUTPUT_DIR/manifest/manifest.json: "operations" is what to do, in
    order, and "files" where every file is once that's done."""
    manifest = {
        "version": 1,
        "at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
        "operations": operations,
        "files": [{"from": f["path"], "to": layout[f["path"]], "size": f["size"]} for f in files],
    }
    folder = os.path.join(output_dir, MANIFEST)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "manifest.json")
    with open(path, "w") as out:
        json.dump(manifest, out, indent=2)
    return path
