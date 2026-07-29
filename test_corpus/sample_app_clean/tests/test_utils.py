from ..utils import calculate_total


def test_calculate_total():
    items = [{"price": 10}, {"price": 5}, {"price": 2.5}]
    assert calculate_total(items) == 17.5


def test_calculate_total_empty():
    assert calculate_total([]) == 0
