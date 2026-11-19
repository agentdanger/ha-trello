"""Constants for the trello integration."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
import logging
from typing import Final

DOMAIN: Final = "trello"

LOGGER = logging.getLogger(__package__)

CONF_USER_ID = "user_id"
CONF_USER_EMAIL = "user_email"
CONF_BOARD_IDS = "board_ids"
# {board_id: [[list_id, list_id, ...], ...]}: the ordered chains of lists a
# card moves along when its to-do item is ticked.
CONF_CHAINS = "chains"

CARD_FIELDS: Final = ["name", "desc", "due", "dueComplete", "pos"]

# Where a card lands in the list it is moved to.
MOVED_CARD_POSITION: Final = "top"
# Ticking an item on the last list of a chain archives the card.
ARCHIVE_AT_END_OF_CHAIN: Final = True
# Trello due dates always carry a time; a due date set without one gets this.
DEFAULT_DUE_TIME: Final = time(9, 0)

SERVICE_MOVE_CARD: Final = "move_card"
ATTR_ITEM: Final = "item"
ATTR_DIRECTION: Final = "direction"
ATTR_LIST: Final = "list"
DIRECTION_NEXT: Final = "next"
DIRECTION_PREVIOUS: Final = "previous"


@dataclass
class Card:
    """A Trello card."""

    id: str
    name: str
    desc: str = ""
    due: str | None = None
    due_complete: bool = False
    pos: float = 0


@dataclass
class List:
    """A Trello list."""

    id: str
    name: str
    card_count: int
    cards: list[Card] = field(default_factory=list)


@dataclass
class Board:
    """A Trello board."""

    id: str
    name: str
    lists: dict[str, List]


@dataclass
class Move:
    """A card move that can be undone."""

    card: Card
    from_list_id: str
    from_pos: float
    archived: bool
