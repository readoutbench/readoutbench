"""The time-to-event width floor is pooled within one scale: log-scale medians and %-event-rate controls apart."""
from tdcb.trials import numbers as tnum

BASE = {"kind": "time_to_event", "effect_measure": "hazard ratio, experimental vs control", "better": "lower",
        "experimental_arm": "a", "control_arm": "b", "n_experimental": 100, "n_control": 100, "design": "superiority",
        "numbers": "yes"}


def test_event_rate_controls_get_a_percentage_point_floor():
    cards, ref = {}, {}
    eff = {"median": 0.8, "low80": 0.6, "high80": 1.0}
    for i in range(10):            # median-time controls: log scale, widths ln 2
        cards[f"M{i}"] = dict(BASE, nct_id=f"M{i}", unit="months", control_measure="median overall survival")
        ref[f"M{i}"] = {"control": {"median": 10, "low80": 7.07, "high80": 14.14}, "effect": eff}
    for i in range(10):            # %-event-rate controls: linear, widths 10 to 19 points
        cards[f"R{i}"] = dict(BASE, nct_id=f"R{i}", unit="% of patients",
                              control_measure="% of control patients with an event by 2 years (event rate at 24 months)")
        ref[f"R{i}"] = {"control": {"median": 30, "low80": 25, "high80": 35 + i}, "effect": eff}
    assert all(tnum.is_number_question(c) for c in cards.values())
    assert tnum.log_scale(cards["M0"], "control") and not tnum.log_scale(cards["R0"], "control")
    f = tnum.width_floors(ref, cards)
    assert f[("R0", "control")] >= 10          # a percentage-point floor from the event-rate pool, not ln 2
    assert f[("M0", "control")] < 1            # a log-scale floor


def test_count_rate_controls_are_pooled_apart_from_percentages():
    cards, ref = {}, {}
    eff = {"median": 0.8, "low80": 0.6, "high80": 1.0}
    for i in range(10):            # %-event-rate controls, widths 10 to 19 points
        cards[f"P{i}"] = dict(BASE, nct_id=f"P{i}", unit="% of patients",
                              control_measure="% of control patients with an event by 2 years (event rate at 24 months)")
        ref[f"P{i}"] = {"control": {"median": 30, "low80": 25, "high80": 35 + i}, "effect": eff}
    for i in range(10):            # count-rate controls, widths 0.2 to 0.29 events per patient-year
        cards[f"C{i}"] = dict(BASE, nct_id=f"C{i}", unit="events per patient-year",
                              control_measure="annualised rate of events per patient-year in the control arm")
        ref[f"C{i}"] = {"control": {"median": 0.5, "low80": 0.4, "high80": 0.6 + i / 100}, "effect": eff}
    assert not tnum.log_scale(cards["C0"], "control") and not tnum.log_scale(cards["P0"], "control")
    f = tnum.width_floors(ref, cards)
    assert f[("P0", "control")] >= 10          # the percentage pool's floor
    assert f[("C0", "control")] < 1            # the count-rate pool's own floor, not percentage points
