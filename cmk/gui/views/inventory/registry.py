#!/usr/bin/env python3
# Copyright (C) 2019 Checkmk GmbH - License: GNU General Public License v2
# This file is part of Checkmk (https://checkmk.com). It is subject to the terms and
# conditions defined in the file COPYING, which is part of this source code package.

from __future__ import annotations

import abc
from collections.abc import Sequence
from typing import Any, Callable, Protocol, TypeVar

from typing_extensions import TypedDict

from cmk.utils.plugin_registry import Registry

from cmk.gui.utils.html import HTML
from cmk.gui.utils.speaklater import LazyString


class _Comparable(Protocol):
    # TODO This protocol can also be used in cmk.utils.structured_data.py
    @abc.abstractmethod
    def __eq__(self, other: object) -> bool: ...

    @abc.abstractmethod
    def __lt__(self, other: InvValue) -> bool: ...

    @abc.abstractmethod
    def __gt__(self, other: InvValue) -> bool: ...


InvValue = TypeVar("InvValue", bound=_Comparable)
SortFunction = Callable[[InvValue, InvValue], int]


class InventoryHintSpec(TypedDict, total=False):
    title: str | LazyString
    short: str | LazyString
    icon: str
    paint: str
    view: str
    keyorder: Sequence[str]
    sort: SortFunction
    filter: Any
    is_show_more: bool


InventoryHintRegistry = dict[str, InventoryHintSpec]
inventory_displayhints: InventoryHintRegistry = {}


PaintResult = tuple[str, str | HTML]
PaintFunction = Callable[[Any], PaintResult]


class InvPaintFunction(TypedDict):
    name: str
    func: PaintFunction


class InvPaintFunctions(Registry[InvPaintFunction]):
    def plugin_name(self, instance: InvPaintFunction) -> str:
        return instance["name"]


inv_paint_funtions = InvPaintFunctions()
