import re

_PREFIX = re.compile(r"^(?:bot-|tw-)", re.IGNORECASE)


def normalise_block_id(value: str) -> str:
    """Return the numeric part of an Adsun block ID.

    Adsun accepts ``50001``, ``bot-50001`` and ``tw-50001``. Normalising the
    callback value keeps the idempotency key stable if the provider changes
    between the prefixed and numeric forms across retries.
    """
    cleaned = value.strip()
    if not cleaned:
        return ""
    numeric = _PREFIX.sub("", cleaned)
    if not numeric.isascii() or not numeric.isdigit():
        raise ValueError("block id must be numeric, e.g. 50001, bot-50001 or tw-50001")
    return numeric
