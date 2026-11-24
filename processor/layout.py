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

# When the files come from a dataset view, the platform puts the view's
# description at INPUT_DIR/.pennsieve/view.json. It isn't one of the person's
# files, so it's never listed.
VIEW_DIR = ".pennsieve"
VIEW_FILE = "view.json"


def input_files(input_dir):
    """Every file below INPUT_DIR: [{"path", "size"}], path relative to it."""
    files = []
    for dirpath, dirnames, filenames in os.walk(input_dir, followlinks=True):
        dirnames[:] = [d for d in dirnames if d != VIEW_DIR]
        for name in filenames:
            full = os.path.join(dirpath, name)
            path = os.path.relpath(full, input_dir).replace(os.sep, "/")
            files.append({"path": path, "size": os.path.getsize(full)})
    return sorted(files, key=lambda f: f["path"])


def input_view(input_dir):
    """The dataset view the files came from, {"id", "version"}, or None when
    they didn't come from one. The view lists the files flat, as the person
    picked them; the step that executes the manifest uses this to ask where
    each one really is in the dataset."""
    try:
        with open(os.path.join(input_dir, VIEW_DIR, VIEW_FILE)) as f:
            graph = json.load(f).get("@graph") or []
        root = next(e for e in graph if isinstance(e, dict) and e.get("@id") == "./")
        return {"id": str(root["identifier"]), "version": int(root["version"])}
    except (OSError, ValueError, KeyError, StopIteration, TypeError, AttributeError):
        return None


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
        self.placeholders = set()  # files made here, for ones that are missing
        self.folders = set()
        for path in self.files:
            parts = path.split("/")[:-1]
            self.folders.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))

    def kind(self, path):
        """"file", "folder", or "" when nothing is at the path."""
        if path in self.files.values() or path in self.placeholders:
            return "file"
        return "folder" if path in self.folders else ""

    def relocate(self, old, new):
        """Put the file or folder at old, and all that's in it, at new."""
        moved = lambda p: new if p == old else new + p[len(old):] if p.startswith(old + "/") else p
        self.files = {src: moved(cur) for src, cur in self.files.items()}
        self.placeholders = {moved(p) for p in self.placeholders}
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
      {"op": "create_file", "path": "archive/.readme.md", "for": "readme.md"}

    create_file makes an empty placeholder for a file that is missing ("for"
    names it). It isn't one of the input files, so it isn't in the layout.
    """
    tree = _Tree(files)
    done = []
    for n, op in enumerate(operations, start=1):
        if not isinstance(op, dict):
            return None, None, f"operation {n} isn't an operation"
        what, path = op.get("op"), op.get("path")
        if not isinstance(path, str) or not path:
            return None, None, f"operation {n} has no path"

        if what in ("create_folder", "create_file"):
            why = next((w for w in map(_bad_name, path.split("/")) if w), "")
            if why:
                return None, None, f"operation {n}: the {what[7:]}'s path {why}"
            if tree.kind(path):
                return None, None, f"operation {n}: {path!r} already exists"
            if _parent(path) and tree.kind(_parent(path)) != "folder":
                return None, None, f"operation {n}: {_parent(path)!r} isn't a folder"
            record = {"op": what, "path": path}
            if what == "create_folder":
                tree.folders.add(path)
            else:
                tree.placeholders.add(path)
                if isinstance(op.get("for"), str) and not _bad_name(op["for"]):
                    record["for"] = op["for"]
            done.append(record)
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


def write_manifest(output_dir, files, layout, operations, notes, view=None):
    """Write OUTPUT_DIR/manifest/manifest.json: "operations" is what to do, in
    order, and "files" where every file is once that's done. "view" is the
    dataset view the files came from (input_view), when they came from one."""
    manifest = {
        "version": 1,
        "at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
        "operations": operations,
        "files": [{"from": f["path"], "to": layout[f["path"]], "size": f["size"]} for f in files],
    }
    if view:
        manifest["view"] = view
    folder = os.path.join(output_dir, MANIFEST)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "manifest.json")
    with open(path, "w") as out:
        json.dump(manifest, out, indent=2)
    return path
