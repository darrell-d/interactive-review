"""The review's inputs and outputs: what is listed, what review.json says,
and where the approved files land."""

import json
import os
import tempfile
import unittest

from processor.review import copy_approved, input_files, write_review


def write(root, path, text="x"):
    full = os.path.join(root, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(text)


class ReviewFilesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.input_dir = os.path.join(tmp.name, "input")
        self.output_dir = os.path.join(tmp.name, "output")
        write(self.input_dir, "sub-02/volumes.csv", "a,b\n")
        write(self.input_dir, "sub-01/volumes.csv", "a,b,c\n")
        write(self.input_dir, "provenance.json", "{}")

    def test_input_files_are_relative_and_sorted(self):
        files = input_files(self.input_dir)
        self.assertEqual(
            [f["path"] for f in files],
            ["provenance.json", "sub-01/volumes.csv", "sub-02/volumes.csv"],
        )
        self.assertEqual(files[1]["size"], len("a,b,c\n"))

    def test_review_json_has_a_decision_for_every_file(self):
        files = input_files(self.input_dir)
        path = write_review(self.output_dir, files, {"sub-01/volumes.csv"}, "sub-02 looks off")
        self.assertEqual(path, os.path.join(self.output_dir, "review", "review.json"))
        with open(path) as f:
            review = json.load(f)
        self.assertEqual(review["notes"], "sub-02 looks off")
        self.assertEqual(
            {f["path"]: f["decision"] for f in review["files"]},
            {
                "provenance.json": "rejected",
                "sub-01/volumes.csv": "approved",
                "sub-02/volumes.csv": "rejected",
            },
        )

    def test_approved_files_keep_their_paths(self):
        copy_approved(self.input_dir, self.output_dir, {"sub-01/volumes.csv", "provenance.json"})
        approved = input_files(os.path.join(self.output_dir, "approved"))
        self.assertEqual([f["path"] for f in approved], ["provenance.json", "sub-01/volumes.csv"])
        with open(os.path.join(self.output_dir, "approved", "sub-01", "volumes.csv")) as f:
            self.assertEqual(f.read(), "a,b,c\n")


if __name__ == "__main__":
    unittest.main()
