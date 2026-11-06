from reports import sales_total


def test_sales_total():
    assert sales_total([{'total': 10.5}, {'total': 4.5}]) == 15.0
