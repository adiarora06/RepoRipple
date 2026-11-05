from checkout_demo.billing.store import reserve_inventory


def test_reserves_inventory():
    assert reserve_inventory("sku-123", 2)["reserved"] is True
