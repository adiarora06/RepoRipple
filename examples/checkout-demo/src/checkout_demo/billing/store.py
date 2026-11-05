"""Persistence boundary for checkout reservations."""


def reserve_inventory(sku: str, quantity: int) -> dict[str, object]:
    return {"sku": sku, "quantity": quantity, "reserved": True}
