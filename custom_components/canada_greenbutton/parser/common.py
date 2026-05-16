"""XML helpers ported from xml-parser.service.ts."""
from __future__ import annotations

from typing import Iterable, Iterator, Optional
from xml.etree.ElementTree import Element


def _local(tag: str) -> str:
    """Strip XML namespace from element tag."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def by_local_name(root: Element, name: str) -> Optional[Element]:
    """First descendant (any depth) with matching local name."""
    for el in root.iter():
        if _local(el.tag) == name:
            return el
    return None


def all_by_local_name(root: Element, name: str) -> list[Element]:
    """All descendants (any depth) with matching local name."""
    return [el for el in root.iter() if _local(el.tag) == name]


def direct_children(el: Element, name: str) -> list[Element]:
    """Immediate children only, matching local name."""
    return [c for c in list(el) if _local(c.tag) == name]


def child(el: Element, name: str) -> Optional[Element]:
    """First descendant of `el` with matching local name."""
    for sub in el.iter():
        if sub is el:
            continue
        if _local(sub.tag) == name:
            return sub
    return None


def child_text(el: Element, name: str) -> Optional[str]:
    """Text of first descendant matching name; trimmed; None if absent/empty."""
    sub = child(el, name)
    if sub is None or sub.text is None:
        return None
    text = sub.text.strip()
    return text or None


def child_int(el: Element, name: str) -> Optional[int]:
    """Integer of first descendant matching name; None if missing/non-numeric."""
    text = child_text(el, name)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def iter_local(root: Element, name: str) -> Iterator[Element]:
    for el in root.iter():
        if _local(el.tag) == name:
            yield el


def first_in(els: Iterable[Element], name: str) -> Optional[Element]:
    for el in els:
        if _local(el.tag) == name:
            return el
    return None
