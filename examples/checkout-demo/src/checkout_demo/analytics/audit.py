"""Audit adapter for reservation behavior."""

from checkout_demo.billing.service import reserve_order


def preview_reservation(sku: str) -> dict[str, object]:
    return reserve_order(sku, 1)
