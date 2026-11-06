import orders


def test_order_total():
    o = orders.create_order([('tea', 2)], 10)
    assert o['total'] == 216.0
