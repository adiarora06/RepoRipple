"""Checkout reservation rules."""

from checkout_demo.billing.store import reserve_inventory


def reserve_order(sku: str, quantity: int) -> dict[str, object]:
    if quantity < 1:
        raise ValueError("quantity must be positive")
    return reserve_inventory(sku, quantity)
