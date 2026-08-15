"""Turning grocery lines into rows a human reads.

The pipeline keeps quantities separated by dimension — you can't add "1 cup
chopped onion" to "1 onion" without inventing a conversion — but two rows
labelled *Yellow onions* read as a bug to whoever is holding the list. So the
split survives in the quantity, not in the row count.
"""

from __future__ import annotations

from typing import Iterable

from .parse import format_qty


def collapse_rows(lines: Iterable) -> list[tuple[str, str]]:
    """[(display_name, quantity label)] — one row per item, quantities joined."""
    order: list[str] = []
    quantities: dict[str, list[str]] = {}
    for line in lines:
        name = line.display_name
        if name not in quantities:
            order.append(name)
            quantities[name] = []
        pretty = format_qty(line.qty, line.unit)
        if pretty and pretty not in quantities[name]:
            quantities[name].append(pretty)
    return [(name, " + ".join(quantities[name])) for name in order]
