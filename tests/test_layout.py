"""The layout: what is listed, which operations are accepted, and what the
manifest says."""

import json
import os
import tempfile
import unittest

from processor.layout import input_files, replay, write_manifest

FILES = [
    {"path": "notes.txt", "size": 3},
    {"path": "raw/a.csv", "size": 5},
    {"path": "raw/b.csv", "size": 7},
]


class InputFilesTest(unittest.TestCase):
    def test_input_files_are_relative_and_sorted(self):
        with tempfile.TemporaryDirectory() as root:
            for path, text in (("raw/b.csv", "a,b,c\n"), ("raw/a.csv", "a\n"), ("notes.txt", "hi")):
                full = os.path.join(root, path)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w") as f:
                    f.write(text)
            files = input_files(root)
        self.assertEqual([f["path"] for f in files], ["notes.txt", "raw/a.csv", "raw/b.csv"])
        self.assertEqual(files[2]["size"], len("a,b,c\n"))


class ReplayTest(unittest.TestCase):
    def test_no_operations_leaves_every_file_where_it_is(self):
        layout, operations, why = replay(FILES, [])
        self.assertEqual(why, "")
        self.assertEqual(operations, [])
        self.assertEqual(layout, {"notes.txt": "notes.txt", "raw/a.csv": "raw/a.csv", "raw/b.csv": "raw/b.csv"})

    def test_operations_apply_in_order_to_what_the_ones_before_left(self):
        layout, operations, why = replay(FILES, [
            {"op": "rename", "path": "raw", "name": "source"},
            {"op": "rename", "path": "source/a.csv", "name": "eeg.csv"},
            {"op": "create_folder", "path": "archive"},
            {"op": "move", "path": "notes.txt", "to": "archive"},
            {"op": "move", "path": "archive", "to": "source"},
            {"op": "move", "path": "source/b.csv", "to": ""},
        ])
        self.assertEqual(why, "")
        self.assertEqual(layout, {
            "notes.txt": "source/archive/notes.txt",
            "raw/a.csv": "source/eeg.csv",
            "raw/b.csv": "b.csv",
        })
        # Each is written back with what was at its path.
        self.assertEqual(operations, [
            {"op": "rename", "kind": "folder", "path": "raw", "name": "source"},
            {"op": "rename", "kind": "file", "path": "source/a.csv", "name": "eeg.csv"},
            {"op": "create_folder", "path": "archive"},
            {"op": "move", "kind": "file", "path": "notes.txt", "to": "archive"},
            {"op": "move", "kind": "folder", "path": "archive", "to": "source"},
            {"op": "move", "kind": "file", "path": "source/b.csv", "to": ""},
        ])

    def test_a_folder_emptied_by_a_move_is_still_a_folder(self):
        layout, _, why = replay(FILES, [
            {"op": "move", "path": "raw/a.csv", "to": ""},
            {"op": "move", "path": "raw/b.csv", "to": ""},
            {"op": "move", "path": "notes.txt", "to": "raw"},
        ])
        self.assertEqual(why, "")
        self.assertEqual(layout["notes.txt"], "raw/notes.txt")

    def test_refuses_what_can_not_be_done(self):
        cases = {
            "not an operation": ["rename"],
            "an operation this app doesn't do": [{"op": "delete", "path": "notes.txt"}],
            "no path": [{"op": "rename", "name": "x"}],
            "nothing at the path": [{"op": "rename", "path": "other.csv", "name": "x.csv"}],
            "a path from before an earlier rename": [
                {"op": "rename", "path": "raw", "name": "source"},
                {"op": "rename", "path": "raw/a.csv", "name": "x.csv"},
            ],
            "a name with a slash": [{"op": "rename", "path": "notes.txt", "name": "a/notes.txt"}],
            "a name that climbs out": [{"op": "rename", "path": "notes.txt", "name": ".."}],
            "an empty name": [{"op": "rename", "path": "notes.txt", "name": " "}],
            "a name that isn't text": [{"op": "rename", "path": "notes.txt", "name": 3}],
            "a name already taken": [{"op": "rename", "path": "raw/a.csv", "name": "b.csv"}],
            "a file renamed onto a folder": [{"op": "rename", "path": "notes.txt", "name": "raw"}],
            "a move into something that isn't a folder": [{"op": "move", "path": "raw/a.csv", "to": "notes.txt"}],
            "a move into a folder that doesn't exist": [{"op": "move", "path": "notes.txt", "to": "archive"}],
            "a move with no destination": [{"op": "move", "path": "notes.txt"}],
            "a move onto a taken name": [
                {"op": "rename", "path": "notes.txt", "name": "a.csv"},
                {"op": "move", "path": "a.csv", "to": "raw"},
            ],
            "a folder into itself": [{"op": "move", "path": "raw", "to": "raw"}],
            "a folder into its own subfolder": [
                {"op": "create_folder", "path": "raw/deep"},
                {"op": "move", "path": "raw", "to": "raw/deep"},
            ],
            "a folder that already exists": [{"op": "create_folder", "path": "raw"}],
            "a folder where a file is": [{"op": "create_folder", "path": "notes.txt"}],
            "a folder inside one that doesn't exist": [{"op": "create_folder", "path": "x/y"}],
            "a folder outside the input": [{"op": "create_folder", "path": "../x"}],
        }
        for name, operations in cases.items():
            layout, done, why = replay(FILES, operations)
            self.assertIsNone(layout, name)
            self.assertIsNone(done, name)
            self.assertTrue(why, name)


class ManifestTest(unittest.TestCase):
    def test_manifest_has_the_instructions_and_where_every_file_ends_up(self):
        layout, operations, _ = replay(FILES, [{"op": "rename", "path": "raw", "name": "source"}])
        with tempfile.TemporaryDirectory() as out:
            path = write_manifest(out, FILES, layout, operations, "tidied up")
            self.assertEqual(path, os.path.join(out, "manifest", "manifest.json"))
            with open(path) as f:
                manifest = json.load(f)
        self.assertEqual(manifest["version"], 1)
        self.assertEqual(manifest["notes"], "tidied up")
        self.assertEqual(manifest["operations"], [{"op": "rename", "kind": "folder", "path": "raw", "name": "source"}])
        self.assertEqual(
            manifest["files"],
            [
                {"from": "notes.txt", "to": "notes.txt", "size": 3},
                {"from": "raw/a.csv", "to": "source/a.csv", "size": 5},
                {"from": "raw/b.csv", "to": "source/b.csv", "size": 7},
            ],
        )


if __name__ == "__main__":
    unittest.main()
