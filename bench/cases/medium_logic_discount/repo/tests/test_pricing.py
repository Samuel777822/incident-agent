from pricing import apply_discount, line_total


def test_discount():
    assert apply_discount(200, 10) == 180


def test_line():
    assert line_total(100, 3, 10) == 270
