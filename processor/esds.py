"""Arranging the input files as an ESDS dataset (the Epilepsy.Science data
structure, which follows BIDS): the folders to make, where each recording
file goes and under what name, and which files the layout expects that
aren't here.

It only proposes. The result is a list of the organizer's own operations
(layout.replay), which the page shows and the person can still change, plus
a placeholder for each missing file: an empty file whose name is the missing
one's with a dot in front, where the real one will go.

The layout is data, esds_layout.json: one recording of one subject, with
{subject}, {session}, {task} and {acq} in its paths.
"""

import json
import os
import posixpath
import re

with open(os.path.join(os.path.dirname(__file__), "esds_layout.json")) as _f:
    LAYOUT = json.load(_f)

# A BIDS label: letters and digits (a dot is allowed inside, as in
# ses-visit01.5m). No spaces, dashes or underscores: those separate labels.
_LABEL = re.compile(r"^[A-Za-z0-9]+(\.[A-Za-z0-9]+)*$")


def read_labels(given):
    """The labels to name things with, from what the person typed:
    ({name: value}, "") or (None, why not). An optional one may be empty."""
    labels = {}
    for spec in LAYOUT["labels"]:
        name = spec["name"]
        value = given.get(name)
        value = (value if isinstance(value, str) else "").strip() or spec.get("default", "")
        if value.lower().startswith(spec["prefix"]):
            value = value[len(spec["prefix"]):]  # "sub-X" typed for X
        if not value:
            if spec.get("optional"):
                labels[name] = ""
                continue
            return None, f"the {name} is needed"
        if not _LABEL.match(value):
            return None, f"the {name} {value!r} can only have letters and digits"
        labels[name] = value
    return labels, ""


def fill(pattern, labels):
    """A path of the layout with the labels in. An optional label left empty
    takes its whole part out: "_acq-{acq}" is dropped, not left as "_acq-"."""
    for name, value in labels.items():
        if not value:
            pattern = re.sub(r"_[a-z]+-\{%s\}" % name, "", pattern)
        pattern = pattern.replace("{%s}" % name, value)
    return pattern


def channel_name(name):
    """The channel a recording file is named for: "EEG AD 01-Ref.mef" is
    AD01.mef. Only a guess from the name; the person can rename it."""
    stem, ext = posixpath.splitext(name)
    stem = re.sub(r"^EEG[ _-]+", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"[ _-]+Ref$", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"\s+", "", stem)
    return stem + ext.lower() if stem else name


def arrange(files, labels):
    """The operations that put the input files in the layout.

    Returns {"operations", "missing", "expected", "notes"}: the operations
    in the organizer's form, starting from the files as they came; "missing"
    the expected files that aren't among them, each with the placeholder
    made for it ({"path", "placeholder", "what"}), out of "expected" in all;
    "notes" what else the person should know, in plain sentences.
    """
    operations, missing, notes = [], [], []
    at = {f["path"]: f["path"] for f in files}  # where each input file is now
    folders = set()
    for path in at:
        parts = path.split("/")[:-1]
        folders.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))

    def taken(path):
        return path in at.values() or path in folders

    def make_folder(folder):
        parts = folder.split("/") if folder else []
        for i in range(1, len(parts) + 1):
            path = "/".join(parts[:i])
            if path not in folders:
                operations.append({"op": "create_folder", "path": path})
                folders.add(path)

    def move(src, folder):
        """Move the input file that came as src into folder; False when a
        file of that name is already there."""
        new = posixpath.join(folder, posixpath.basename(at[src]))
        if new == at[src]:
            return True
        if taken(new):
            return False
        make_folder(folder)
        operations.append({"op": "move", "path": at[src], "to": folder})
        at[src] = new
        return True

    # 1. The recording's files go into its folder, each under its channel's
    #    name.
    recording = fill(LAYOUT["recording"], labels).rstrip("/")
    endings = tuple(LAYOUT["recordingFiles"])
    channels = sorted(p for p in at if p.lower().endswith(endings))
    if not channels:
        notes.append(f"None of the files is a recording file ({', '.join(endings)}), so the recording's folder stays empty.")
    make_folder(recording)
    for src in channels:
        name = posixpath.basename(src)
        clean = channel_name(name)
        if clean != name:
            renamed = posixpath.join(posixpath.dirname(src), clean)
            if taken(renamed) or taken(posixpath.join(recording, clean)):
                notes.append(f"{name} keeps its name: another file would also be {clean}.")
            else:
                operations.append({"op": "rename", "path": src, "name": clean})
                at[src] = renamed
        if not move(src, recording):
            notes.append(f"{posixpath.basename(at[src])} stays where it is: the recording already has a file of that name.")

    # 2. Each file the layout expects: the input file of that name goes to
    #    its place, or a placeholder is made there.
    placed = set(channels)
    for entry in LAYOUT["entries"]:
        path = fill(entry["path"], labels)
        folder, name = posixpath.dirname(path), posixpath.basename(path)
        have = sorted(p for p in at if p not in placed and posixpath.basename(at[p]) == name)
        if have and move(have[0], folder):
            placed.add(have[0])
            continue
        placeholder = posixpath.join(folder, "." + name)
        missing.append({"path": path, "placeholder": placeholder, "what": entry.get("what", "")})
        already = [p for p in at if at[p] == placeholder]
        if already:
            placed.add(already[0])  # a placeholder from an earlier pass
            continue
        make_folder(folder)
        operations.append({"op": "create_file", "path": placeholder, "for": name})

    # 3. Anything else isn't part of the layout: say so, and leave it.
    for src in sorted(p for p in at if p not in placed):
        notes.append(f"{at[src]} isn't part of the layout and stays where it is.")
    return {"operations": operations, "missing": missing, "expected": len(LAYOUT["entries"]), "notes": notes}
