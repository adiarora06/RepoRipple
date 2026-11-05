"""Web-facing checkout route."""

from checkout_demo.api.checkout import create_checkout


def post_checkout(payload: dict[str, object]) -> dict[str, object]:
    return create_checkout(payload)
