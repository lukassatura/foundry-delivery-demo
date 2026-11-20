import pytest

from report_compare import InputError, find_deviations, parse_request


def request_text(baseline: str, current: str, threshold: str = "Threshold: 10%") -> str:
    return f"{threshold}\nBaseline:\n{baseline}\nCurrent:\n{current}\n"


def test_reads_threshold_and_both_reports():
    request = parse_request(request_text("item,amount\nTravel,1000", "item,amount,note\nTravel,1250,Workshops"))
    assert request.threshold_pct == 10
    assert request.baseline["Travel"].amount == 1000
    assert request.current["Travel"].note == "Workshops"


def test_uses_default_threshold_when_line_is_missing():
    request = parse_request(request_text("item,amount\nTravel,1", "item,amount\nTravel,1", threshold=""))
    assert request.threshold_pct == 10


def test_rejects_missing_current_report():
    with pytest.raises(InputError, match="current report is missing"):
        parse_request("Baseline:\nitem,amount\nTravel,1000\n")


def test_rejects_non_numeric_amount():
    with pytest.raises(InputError, match="not a number"):
        parse_request(request_text("item,amount\nTravel,1000", "item,amount\nTravel,n/a"))


def test_flags_increase_and_decrease_above_threshold():
    request = parse_request(
        request_text(
            "item,amount\nTravel,1000\nMarketing,4000\nRent,5000",
            "item,amount\nTravel,1250\nMarketing,2800\nRent,5100",
        )
    )
    assert [d.item for d in find_deviations(request)] == ["Marketing", "Travel"]


def test_ignores_change_below_threshold():
    request = parse_request(request_text("item,amount\nUtilities,1000", "item,amount\nUtilities,1099"))
    assert find_deviations(request) == []


def test_flags_amount_that_starts_from_zero():
    request = parse_request(request_text("item,amount\nTraining,0", "item,amount\nTraining,500"))
    assert [d.item for d in find_deviations(request)] == ["Training"]


def test_reports_item_missing_from_current_report():
    request = parse_request(request_text("item,amount\nPrinting,300\nTravel,1000", "item,amount\nTravel,1000"))
    [deviation] = find_deviations(request)
    assert (deviation.item, deviation.kind) == ("Printing", "removed")


def test_reports_item_new_in_current_report():
    request = parse_request(request_text("item,amount\nTravel,1000", "item,amount,note\nTravel,1000,\nCloud hosting,2400,Test site"))
    [deviation] = find_deviations(request)
    assert (deviation.item, deviation.kind, deviation.note) == ("Cloud hosting", "new", "Test site")
