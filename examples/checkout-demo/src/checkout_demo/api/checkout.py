"""Request adapter for checkout reservations."""

from checkout_demo.billing.service import reserve_order


def create_checkout(payload: dict[str, object]) -> dict[str, object]:
    return reserve_order(str(payload["sku"]), int(payload["quantity"]))
