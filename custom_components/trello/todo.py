"""To-do lists for the Trello integration: one per Trello list."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import voluptuous as vol

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_DIRECTION,
    ATTR_ITEM,
    ATTR_LIST,
    DEFAULT_DUE_TIME,
    DIRECTION_NEXT,
    DIRECTION_PREVIOUS,
    DOMAIN,
    SERVICE_MOVE_CARD,
    Board,
    Card,
    List,
)
from .coordinator import TrelloDataUpdateCoordinator

MOVE_CARD_SCHEMA: dict[Any, Any] = {
    vol.Required(ATTR_ITEM): cv.string,
    vol.Optional(ATTR_DIRECTION): vol.In([DIRECTION_NEXT, DIRECTION_PREVIOUS]),
    vol.Optional(ATTR_LIST): cv.string,
}


class TrelloTodoList(CoordinatorEntity[TrelloDataUpdateCoordinator], TodoListEntity):
    """A Trello list as a to-do list, with a to-do item for each card.

    On a list that is part of a chain every card shows unchecked, and ticking
    one moves it to the next list of the chain. On any other list the checkbox
    is the card's own complete mark.
    """

    _attr_has_entity_name = True
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.MOVE_TODO_ITEM
        | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
        | TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(
        self,
        board: Board,
        list_: List,
        coordinator: TrelloDataUpdateCoordinator,
    ) -> None:
        """Initialize the to-do list."""
        super().__init__(coordinator)
        self.board_id = board.id
        self.list_id = list_.id
        self._attr_unique_id = f"todo_{list_.id}".lower()
        self._attr_name = list_.name

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, board.id)},
            name=board.name,
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="Trello",
            model="Board",
        )

    @property
    def _list(self) -> List | None:
        return self.coordinator.get_list(self.board_id, self.list_id)

    @property
    def _chained(self) -> bool:
        return self.coordinator.get_chain(self.board_id, self.list_id) is not None

    @property
    def available(self) -> bool:
        """The list is gone when it is archived in Trello or the fetch failed."""
        return super().available and self._list is not None

    @property
    def todo_items(self) -> list[TodoItem] | None:
        """Return the list's cards, top to bottom."""
        list_ = self._list
        if list_ is None:
            return None
        chained = self._chained
        return [
            TodoItem(
                uid=card.id,
                summary=card.name,
                status=(
                    TodoItemStatus.COMPLETED
                    if card.due_complete and not chained
                    else TodoItemStatus.NEEDS_ACTION
                ),
                due=_parse_due(card.due),
                description=card.desc or None,
            )
            for card in list_.cards
        ]

    @callback
    def _handle_coordinator_update(self) -> None:
        list_ = self._list
        if list_ is not None:
            self._attr_name = list_.name
        super()._handle_coordinator_update()

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add a card to the bottom of the list."""
        fields: dict[str, Any] = {"name": item.summary}
        if item.description:
            fields["desc"] = item.description
        if item.due:
            fields["due"] = _format_due(item.due)
        await self.coordinator.async_create_card(self.list_id, fields)

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Change a card, and act on its checkbox."""
        card = self._get_card(item.uid)
        chained = self._chained
        fields: dict[str, Any] = {}
        if item.summary and item.summary != card.name:
            fields["name"] = item.summary
        if (item.description or "") != card.desc:
            fields["desc"] = item.description or ""
        if _as_datetime(item.due) != _parse_due(card.due):
            fields["due"] = _format_due(item.due)
        done = item.status == TodoItemStatus.COMPLETED
        if not chained and done != card.due_complete:
            fields["dueComplete"] = done
        if fields:
            await self.coordinator.async_update_card(card.id, fields)
        if chained and done:
            await self.coordinator.async_advance_card(
                self.board_id, self.list_id, card
            )

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Archive cards. Nothing is deleted from Trello."""
        await self.coordinator.async_archive_cards(uids)

    async def async_move_todo_item(
        self, uid: str, previous_uid: str | None = None
    ) -> None:
        """Move a card up or down within the list."""
        list_ = self._list
        others = [card for card in (list_.cards if list_ else []) if card.id != uid]
        pos: str | float = "top"
        if previous_uid is not None:
            index = next(
                (i for i, card in enumerate(others) if card.id == previous_uid), None
            )
            if index is None:
                raise ServiceValidationError("The card to move after was not found")
            if index + 1 < len(others):
                pos = (others[index].pos + others[index + 1].pos) / 2
            else:
                pos = "bottom"
        await self.coordinator.async_update_card(uid, {"pos": pos})

    async def async_move_card(
        self, item: str, direction: str | None = None, **kwargs: Any
    ) -> None:
        """Move a card along its chain, or to a named list on the same board."""
        to_list: str | None = kwargs.get(ATTR_LIST)
        if (direction is None) == (to_list is None):
            raise ServiceValidationError(
                f"Give one of '{ATTR_DIRECTION}' or '{ATTR_LIST}'"
            )
        card = self._get_card(item)
        if to_list is not None:
            target = self._find_list(to_list)
            await self.coordinator.async_move_card(
                self.board_id, self.list_id, card, target.id
            )
            return
        if not self._chained:
            raise ServiceValidationError("This list is not part of a chain")
        if direction == DIRECTION_NEXT:
            await self.coordinator.async_advance_card(
                self.board_id, self.list_id, card
            )
        else:
            await self.coordinator.async_retreat_card(
                self.board_id, self.list_id, card
            )

    def _get_card(self, uid_or_name: str | None) -> Card:
        list_ = self._list
        for card in list_.cards if list_ else []:
            if uid_or_name in (card.id, card.name):
                return card
        raise ServiceValidationError(f"No card '{uid_or_name}' in this list")

    def _find_list(self, id_or_name: str) -> List:
        board = self.coordinator.data[self.board_id]
        for list_ in board.lists.values():
            if list_.id == self.list_id:
                continue
            if id_or_name == list_.id or id_or_name.casefold() == list_.name.casefold():
                return list_
        raise ServiceValidationError(
            f"No other list '{id_or_name}' on the board {board.name}"
        )


def _parse_due(due: str | None) -> datetime | None:
    """Read a Trello due date, which is always a time in UTC."""
    parsed = dt_util.parse_datetime(due) if due else None
    return dt_util.as_local(parsed) if parsed else None


def _as_datetime(due: date | datetime | None) -> datetime | None:
    """Give a due date with no time the default time of day."""
    if due is None:
        return None
    if isinstance(due, datetime):
        return dt_util.as_local(due)
    return datetime.combine(due, DEFAULT_DUE_TIME, dt_util.get_default_time_zone())


def _format_due(due: date | datetime | None) -> str | None:
    as_datetime = _as_datetime(due)
    return dt_util.as_utc(as_datetime).isoformat() if as_datetime else None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a to-do list for each Trello list."""
    trello_coordinator: TrelloDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]

    async_add_entities(
        TrelloTodoList(board, list_, trello_coordinator)
        for board in trello_coordinator.data.values()
        for list_ in board.lists.values()
    )

    entity_platform.async_get_current_platform().async_register_entity_service(
        SERVICE_MOVE_CARD, MOVE_CARD_SCHEMA, "async_move_card"
    )
