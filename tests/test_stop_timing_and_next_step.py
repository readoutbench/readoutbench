"""v17 review: a stop not about efficacy after a pass's deadline is 'no public result' in that pass, not void;
next-step outcomes marked void, or of trials that left the round, are not scored."""
import importlib.util
import os

HERE = os.path.dirname(__file__)
spec = importlib.util.spec_from_file_location(
    "finalize_labels", os.path.join(HERE, "..", "pilot", "round1_rebuild", "finalize_labels.py"))
fl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fl)

STOP = {"reported": "stopped_without_result", "met": "not_reported", "stop_reason": "not about efficacy"}


def test_a_commercial_stop_counts_by_its_date_against_each_pass():
    may = dict(STOP, first_public_date="2027-05-15")
    march = fl.reading(may, as_of="2027-04-01", deadline="2027-03-31")
    june = fl.reading(may, as_of="2027-07-01", deadline="2027-06-30")
    assert march["state"] == "open" and march["first_public_date"] is None      # 0 for p_public_mar
    assert june["state"] == "dropped"                                           # void in June: left by its deadline
    assert fl.label("NCT1", march, {})["reported"] == "no"


def test_a_stop_with_no_public_reason_is_still_not_met():
    r = fl.reading(dict(STOP, stop_reason="no public reason", first_public_date="2027-05-15"),
                   as_of="2027-07-01", deadline="2027-06-30")
    assert r["state"] == "not_met"
