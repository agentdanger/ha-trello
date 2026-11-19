"""Data update coordinator for the Trello integration."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from trello import Board as TrelloBoard
from trello import List as TrelloList
from trello import ResourceUnavailable, TrelloClient, Unauthorized
from trello.batch.board import Board as BatchBoard

from .const import (
    ARCHIVE_AT_END_OF_CHAIN,
    CARD_FIELDS,
    LOGGER,
    MOVED_CARD_POSITION,
    Board,
    Card,
    List,
    Move,
)


class TrelloDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Board]]):
    """Data update coordinator for the Trello integration."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        trello_client: TrelloClient,
        board_ids: list[str],
        chains: dict[str, list[list[str]]] | None = None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass=hass,
            logger=LOGGER,
            name="trello",
            update_interval=timedelta(seconds=60),
        )
        self.client = trello_client
        self.board_ids = board_ids
        self.chains = chains or {}
        # The last move made along each chain, keyed by the chain's first list.
        self.last_moves: dict[str, Move] = {}

    def _update(self) -> dict[str, Board]:
        """Fetch data for all sensors as a batch."""
        batch_requests = []
        for board_id in self.board_ids:
            batch_requests.append(BatchBoard.GetBoard(board_id, ['name']))
            batch_requests.append(
                BatchBoard.GetLists(board_id, ['name'], 'open', CARD_FIELDS)
            )
        LOGGER.debug("Fetching boards lists")
        batch_responses = self.client.fetch_batch(batch_requests)

        return _get_boards(batch_responses, self.board_ids)

    async def _async_update_data(self) -> dict[str, Board]:
        """Send request to the executor."""
        return await self.hass.async_add_executor_job(self._update)

    def get_list(self, board_id: str, list_id: str) -> List | None:
        """Return a list from the last fetch, if it is still there."""
        board = self.data.get(board_id)
        return board.lists.get(list_id) if board else None

    def get_chain(self, board_id: str, list_id: str) -> list[str] | None:
        """Return the chain a list is part of, less any lists that are gone."""
        board = self.data.get(board_id)
        for chain in self.chains.get(board_id, []):
            if list_id in chain:
                return [id_ for id_ in chain if board and id_ in board.lists]
        return None

    async def async_create_card(self, list_id: str, fields: dict[str, Any]) -> None:
        """Add a card to the bottom of a list."""
        await self._async_write(
            "/cards", "POST", {"idList": list_id, "pos": "bottom", **fields}
        )

    async def async_update_card(self, card_id: str, fields: dict[str, Any]) -> None:
        """Change a card."""
        await self._async_write(f"/cards/{card_id}", "PUT", fields)

    async def async_archive_cards(self, card_ids: list[str]) -> None:
        """Archive cards. They can be sent back to the board from Trello."""
        for card_id in card_ids:
            await self._async_write(
                f"/cards/{card_id}", "PUT", {"closed": True}, refresh=False
            )
        await self.async_refresh()

    async def async_move_card(
        self, board_id: str, from_list_id: str, card: Card, to_list_id: str | None
    ) -> None:
        """Move a card to another list, or archive it when there is none.

        A move that starts on a chained list is remembered so it can be undone.
        """
        if to_list_id is None:
            fields: dict[str, Any] = {"closed": True}
        else:
            fields = {"idList": to_list_id, "pos": MOVED_CARD_POSITION}
        chain = self.get_chain(board_id, from_list_id)
        await self._async_write(f"/cards/{card.id}", "PUT", fields, refresh=False)
        if chain:
            self.last_moves[chain[0]] = Move(
                card.id, card.name, from_list_id, card.pos, to_list_id is None
            )
        await self.async_refresh()

    async def async_advance_card(
        self, board_id: str, list_id: str, card: Card
    ) -> None:
        """Move a card to the next list in its chain.

        On the last list of the chain the card is archived, or left where it
        is and marked complete.
        """
        chain = self.get_chain(board_id, list_id) or [list_id]
        index = chain.index(list_id)
        if index + 1 < len(chain):
            await self.async_move_card(board_id, list_id, card, chain[index + 1])
        elif ARCHIVE_AT_END_OF_CHAIN:
            await self.async_move_card(board_id, list_id, card, None)
        else:
            await self.async_update_card(card.id, {"dueComplete": True})

    async def async_retreat_card(
        self, board_id: str, list_id: str, card: Card
    ) -> None:
        """Move a card to the previous list in its chain."""
        chain = self.get_chain(board_id, list_id)
        if not chain:
            raise HomeAssistantError("This list is not part of a chain")
        index = chain.index(list_id)
        if index == 0:
            raise HomeAssistantError("This is the first list of its chain")
        await self.async_move_card(board_id, list_id, card, chain[index - 1])

    async def async_undo_last_move(self, chain_id: str) -> None:
        """Put the last card moved along a chain back where it was."""
        move = self.last_moves.get(chain_id)
        if move is None:
            raise HomeAssistantError("There is no move to undo")
        fields: dict[str, Any] = {"idList": move.from_list_id, "pos": move.from_pos}
        if move.archived:
            fields["closed"] = False
        await self._async_write(f"/cards/{move.card_id}", "PUT", fields, refresh=False)
        del self.last_moves[chain_id]
        await self.async_refresh()

    async def _async_write(
        self, path: str, method: str, fields: dict[str, Any], refresh: bool = True
    ) -> None:
        """Send a change to Trello, then fetch the boards again."""
        try:
            await self.hass.async_add_executor_job(
                lambda: self.client.fetch_json(
                    path, http_method=method, post_args=fields
                )
            )
        except Unauthorized as ex:
            raise HomeAssistantError(
                "Trello refused the change. The API token needs write access."
            ) from ex
        except ResourceUnavailable as ex:
            raise HomeAssistantError(f"Trello did not make the change: {ex}") from ex
        if refresh:
            await self.async_refresh()


def _get_boards(batch_response: list[dict], board_ids: list[str]) -> dict[str, Board]:
    board_id_boards: dict[str, Board] = {}
    for i, batch_response_pair in enumerate(
        zip(batch_response[::2], batch_response[1::2])
    ):
        board_response = batch_response_pair[0]
        list_response = batch_response_pair[1]
        if board_response.success and list_response.success:
            board = board_response.payload
            lists = list_response.payload
            board_id_boards[board.id] = _get_board(board, lists)
        else:
            LOGGER.error(
                "Unable to fetch lists for board with ID '%s'. Response was: %s)",
                board_ids[i],
                board_response.payload.message,
            )
            board_id_boards[board_ids[i]] = Board(board_ids[i], "", {})
            continue

    return board_id_boards


def _get_board(board: TrelloBoard, lists: list[TrelloList]) -> Board:
    return Board(
        board.id,
        board.name,
        {
            list_.id: List(list_.id, list_.name, len(list_.cards), _get_cards(list_))
            for list_ in lists
        },
    )


def _get_cards(list_: TrelloList) -> list[Card]:
    cards = [
        Card(
            card.id,
            card.name or "",
            card.desc or "",
            card.due or None,
            bool(card.is_due_complete),
            card.pos or 0,
        )
        for card in list_.cards
    ]
    return sorted(cards, key=lambda card: card.pos)
