from checkout_demo.api.checkout import create_checkout


def test_creates_checkout():
    result = create_checkout({"sku": "sku-123", "quantity": 2})

    assert result["quantity"] == 2
