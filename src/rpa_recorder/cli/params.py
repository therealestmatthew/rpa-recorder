"""Typer parameter parsers for the `--param key=value` style options.

`replay` (and any future command needing key/value pairs) repeats `--param`
on the command line. Each occurrence is parsed by `parse_key_value`, and
`collect_params` aggregates them into a `dict[str, str]` while rejecting
duplicates (which would silently shadow earlier values).
"""

import typer


def parse_key_value(raw: str) -> tuple[str, str]:
    """Parse `'name=alice'` into `('name', 'alice')`.

    Whitespace around the key is stripped. Values keep internal whitespace
    but are not stripped on either end (callers may legitimately want it).
    The first `=` separates key from value; later `=` characters are part of
    the value (so `'x=a=b'` → `('x', 'a=b')`). Missing `=` is a usage error.
    """
    if "=" not in raw:
        raise typer.BadParameter(f"expected key=value, got {raw!r}")
    key, _, value = raw.partition("=")
    key = key.strip()
    if not key:
        raise typer.BadParameter(f"empty key in {raw!r}")
    return key, value


def collect_params(values: list[str]) -> dict[str, str]:
    """Aggregate repeated `--param key=value` into a `dict`.

    Duplicate keys raise `typer.BadParameter`; silently dropping the earlier
    value is too easy a foot-gun.
    """
    result: dict[str, str] = {}
    for raw in values:
        key, value = parse_key_value(raw)
        if key in result:
            raise typer.BadParameter(f"duplicate key {key!r}")
        result[key] = value
    return result


__all__ = ["collect_params", "parse_key_value"]
