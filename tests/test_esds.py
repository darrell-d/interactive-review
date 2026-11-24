"""Arranging files as an ESDS dataset: the names it builds, where the
recording files go, and what it reports as missing."""

import unittest

from processor.esds import LAYOUT, arrange, channel_name, fill, read_labels
from processor.layout import replay

MEF = [{"path": p, "size": 10} for p in (
    "EEG AD 01-Ref.mef", "EEG AD 02-Ref.mef", "EEG HD 04-Ref.mef", "EEG PT 01-Ref.mef",
)]
LABELS = {"subject": "PennEPI00168", "session": "postimplant", "task": "clinical", "acq": ""}
SES = "primary/sub-PennEPI00168/ses-postimplant"
REC = SES + "/ieeg/sub-PennEPI00168_ses-postimplant_task-clinical_ieeg-mef"


class LabelsTest(unittest.TestCase):
    def test_defaults_fill_in_what_was_left_empty(self):
        labels, why = read_labels({"subject": " PennEPI00168 "})
        self.assertEqual(why, "")
        self.assertEqual(labels, LABELS)

    def test_a_typed_prefix_is_not_doubled(self):
        labels, _ = read_labels({"subject": "sub-X1", "session": "ses-visit01.5m", "acq": "acq-initial"})
        self.assertEqual(labels, {"subject": "X1", "session": "visit01.5m", "task": "clinical", "acq": "initial"})

    def test_refuses_labels_that_would_break_the_names(self):
        self.assertEqual(read_labels({})[1], "the subject is needed")
        for bad in ("Penn EPI", "a_b", "a-b", "a/b", "..", "a."):
            labels, why = read_labels({"subject": bad})
            self.assertIsNone(labels, bad)
            self.assertIn("letters and digits", why, bad)

    def test_an_empty_optional_label_leaves_its_part_out(self):
        pattern = "sub-{subject}_ses-{session}_task-{task}_acq-{acq}_ieeg.json"
        self.assertEqual(fill(pattern, LABELS), "sub-PennEPI00168_ses-postimplant_task-clinical_ieeg.json")
        self.assertEqual(fill(pattern, {**LABELS, "acq": "revision"}),
                         "sub-PennEPI00168_ses-postimplant_task-clinical_acq-revision_ieeg.json")


class ChannelNameTest(unittest.TestCase):
    def test_a_recording_file_is_named_for_its_channel(self):
        cases = {
            "EEG AD 01-Ref.mef": "AD01.mef", "eeg_HD_04_REF.MEF": "HD_04.mef", "AFD1.mef": "AFD1.mef",
            "Ref.mef": "Ref.mef", "EEG.mef": "EEG.mef",
        }
        for name, want in cases.items():
            self.assertEqual(channel_name(name), want, name)


class ArrangeTest(unittest.TestCase):
    def arrange(self, files, labels=LABELS):
        result = arrange(files, labels)
        # What it proposes must be something the organizer accepts.
        layout, operations, why = replay(files, result["operations"])
        self.assertEqual(why, "")
        placeholders = {op["path"] for op in operations if op["op"] == "create_file"}
        return result, layout, placeholders

    def test_recording_files_go_into_the_recording_folder_under_their_channel_names(self):
        result, layout, _ = self.arrange(MEF)
        self.assertEqual(layout, {
            "EEG AD 01-Ref.mef": REC + "/AD01.mef", "EEG AD 02-Ref.mef": REC + "/AD02.mef",
            "EEG HD 04-Ref.mef": REC + "/HD04.mef", "EEG PT 01-Ref.mef": REC + "/PT01.mef",
        })
        self.assertEqual(result["notes"], [])
        # Folders are made one level at a time, each before it's used.
        self.assertEqual([op["path"] for op in result["operations"][:5]], [
            "primary", "primary/sub-PennEPI00168", SES, SES + "/ieeg", REC,
        ])

    def test_every_expected_file_that_is_not_there_gets_a_placeholder(self):
        result, _, placeholders = self.arrange(MEF)
        self.assertEqual(len(result["missing"]), len(LAYOUT["entries"]))
        self.assertEqual(placeholders, {m["placeholder"] for m in result["missing"]})
        self.assertIn(".dataset_description.json", placeholders)
        self.assertIn("primary/sub-PennEPI00168/.sub-PennEPI00168_sessions.tsv", placeholders)
        self.assertIn(SES + "/ieeg/.sub-PennEPI00168_ses-postimplant_task-clinical_channels.tsv", placeholders)
        first = result["missing"][0]
        self.assertEqual(first, {"path": "dataset_description.json", "placeholder": ".dataset_description.json",
                                 "what": "what the dataset is"})

    def test_the_acq_label_goes_into_every_recording_name(self):
        result, layout, placeholders = self.arrange(MEF, {**LABELS, "acq": "initial"})
        rec = SES + "/ieeg/sub-PennEPI00168_ses-postimplant_task-clinical_acq-initial"
        self.assertEqual(layout["EEG AD 01-Ref.mef"], rec + "_ieeg-mef/AD01.mef")
        self.assertIn(SES + "/ieeg/.sub-PennEPI00168_ses-postimplant_task-clinical_acq-initial_ieeg.json", placeholders)

    def test_an_expected_file_that_is_there_is_moved_into_place_not_reported(self):
        files = MEF + [{"path": "incoming/participants.tsv", "size": 3}, {"path": "dataset_description.json", "size": 3}]
        result, layout, placeholders = self.arrange(files)
        self.assertEqual(layout["incoming/participants.tsv"], "participants.tsv")
        self.assertEqual(layout["dataset_description.json"], "dataset_description.json")
        missing = [m["path"] for m in result["missing"]]
        self.assertNotIn("participants.tsv", missing)
        self.assertNotIn("dataset_description.json", missing)
        self.assertNotIn(".participants.tsv", placeholders)

    def test_files_that_are_not_part_of_the_layout_stay_and_are_named(self):
        files = MEF + [{"path": "report.pdf", "size": 9}]
        result, layout, _ = self.arrange(files)
        self.assertEqual(layout["report.pdf"], "report.pdf")
        self.assertEqual(result["notes"], ["report.pdf isn't part of the layout and stays where it is."])

    def test_two_files_of_one_channel_keep_their_names(self):
        files = [{"path": "EEG AD 01-Ref.mef", "size": 1}, {"path": "AD01.mef", "size": 1}]
        result, layout, _ = self.arrange(files)
        self.assertEqual(layout, {"AD01.mef": REC + "/AD01.mef", "EEG AD 01-Ref.mef": REC + "/EEG AD 01-Ref.mef"})
        self.assertIn("EEG AD 01-Ref.mef keeps its name: another file would also be AD01.mef.", result["notes"])

    def test_no_recording_files_still_makes_the_folders_and_says_so(self):
        result, _, placeholders = self.arrange([{"path": "notes.txt", "size": 1}])
        self.assertIn(REC, [op["path"] for op in result["operations"] if op["op"] == "create_folder"])
        self.assertIn("None of the files is a recording file", result["notes"][0])
        self.assertEqual(len(placeholders), len(LAYOUT["entries"]))

    def test_files_already_arranged_need_nothing_more(self):
        _, layout, placeholders = self.arrange(MEF)
        arranged = [{"path": p, "size": 1} for p in list(layout.values()) + sorted(placeholders)]
        result, again, more = self.arrange(arranged)
        self.assertEqual(result["operations"], [])
        self.assertEqual(more, set())
        self.assertEqual(len(result["missing"]), len(LAYOUT["entries"]))  # still missing: only placeholders are there
        self.assertEqual(result["notes"], [])


if __name__ == "__main__":
    unittest.main()
