"""Buttons for the Trello integration: undo the last move along a chain."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, Board
from .coordinator import TrelloDataUpdateCoordinator


class TrelloUndoButton(CoordinatorEntity[TrelloDataUpdateCoordinator], ButtonEntity):
    """Puts the last card moved along a chain back where it was.

    To-do items have one checkbox, which moves a card forward. This is the
    way back. Only the latest move of each chain is kept, and not across a
    restart.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:undo-variant"

    def __init__(
        self,
        board: Board,
        chain: list[str],
        coordinator: TrelloDataUpdateCoordinator,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator)
        self.chain_id = chain[0]
        self._attr_unique_id = f"undo_{chain[0]}".lower()
        names = [board.lists[id_].name for id_ in chain if id_ in board.lists]
        self._attr_name = f"Undo last move ({' > '.join(names)})"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, board.id)},
            name=board.name,
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="Trello",
            model="Board",
        )

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        """Name the card the button would move back."""
        move = self.coordinator.last_moves.get(self.chain_id)
        return {"card": move.card_name} if move else None

    async def async_press(self) -> None:
        """Undo the last move."""
        await self.coordinator.async_undo_last_move(self.chain_id)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an undo button for each chain, and drop those of chains now gone."""
    trello_coordinator: TrelloDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]
    buttons = [
        TrelloUndoButton(board, chain, trello_coordinator)
        for board in trello_coordinator.data.values()
        for chain in trello_coordinator.chains.get(board.id, [])
        if chain
    ]

    registry = er.async_get(hass)
    current = {button.unique_id for button in buttons}
    for entry in er.async_entries_for_config_entry(registry, config_entry.entry_id):
        if entry.domain == "button" and entry.unique_id not in current:
            registry.async_remove(entry.entity_id)

    async_add_entities(buttons)
