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
        created = await self._async_write(
            "/cards", "POST", {"idList": list_id, "pos": "bottom", **fields}
        )
        list_ = self._find_list(list_id)
        if list_ is not None and "id" in created:
            card = Card(
                created["id"],
                created.get("name") or fields.get("name", ""),
                created.get("desc") or "",
                created.get("due") or None,
                bool(created.get("dueComplete")),
            )
            _put_card(list_, card, created.get("pos") or "bottom")
        self._publish()

    async def async_update_card(self, card_id: str, fields: dict[str, Any]) -> None:
        """Change a card."""
        await self._async_write(f"/cards/{card_id}", "PUT", fields)
        self._apply(card_id, fields)
        self._publish()

    async def async_archive_cards(self, card_ids: list[str]) -> None:
        """Archive cards. They can be sent back to the board from Trello."""
        try:
            for card_id in card_ids:
                await self._async_write(f"/cards/{card_id}", "PUT", {"closed": True})
                self._apply(card_id, {"closed": True})
        finally:
            self._publish()

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
        from_pos = card.pos
        await self._async_write(f"/cards/{card.id}", "PUT", fields)
        if chain:
            self.last_moves[chain[0]] = Move(
                card, from_list_id, from_pos, to_list_id is None
            )
        self._apply(card.id, fields)
        self._publish()

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
        await self._async_write(f"/cards/{move.card.id}", "PUT", fields)
        del self.last_moves[chain_id]
        self._apply(move.card.id, fields, move.card)
        self._publish()

    async def _async_write(
        self, path: str, method: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a change to Trello and return what Trello says the card now is."""
        try:
            response = await self.hass.async_add_executor_job(
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
        return response if isinstance(response, dict) else {}

    def _publish(self) -> None:
        """Show a change Trello has accepted, without waiting to read it back.

        The change is made to the data already held and the entities are told
        at once. Reading the board straight after writing to it can return it
        as it was before, which would put a moved card back for a minute. The
        next regular fetch, a minute from now, confirms it.
        """
        self.async_set_updated_data(self.data)

    def _find_list(self, list_id: str) -> List | None:
        for board in self.data.values():
            if list_id in board.lists:
                return board.lists[list_id]
        return None

    def _apply(
        self, card_id: str, fields: dict[str, Any], card: Card | None = None
    ) -> None:
        """Make to the held data the change just written to Trello.

        :param card: the card, when it may not be on a board (it was archived).
        """
        list_ = None
        for board in self.data.values():
            for candidate in board.lists.values():
                for held in candidate.cards:
                    if held.id == card_id:
                        list_, card = candidate, held
        if card is None:
            return
        if "name" in fields:
            card.name = fields["name"]
        if "desc" in fields:
            card.desc = fields["desc"]
        if "due" in fields:
            card.due = fields["due"]
        if "dueComplete" in fields:
            card.due_complete = fields["dueComplete"]
        if not {"closed", "idList", "pos"} & fields.keys():
            return
        if list_ is not None:
            list_.cards.remove(card)
            list_.card_count = len(list_.cards)
        if fields.get("closed"):
            return
        target = self._find_list(fields["idList"]) if "idList" in fields else list_
        if target is not None:
            _put_card(target, card, fields.get("pos", card.pos))


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

def _put_card(list_: List, card: Card, pos: str | float) -> None:
    """Put a card in a list at "top", "bottom", or a position number."""
    positions = [other.pos for other in list_.cards]
    if pos == "top":
        card.pos = min(positions) / 2 if positions else 65536
    elif pos == "bottom":
        card.pos = max(positions) + 65536 if positions else 65536
    else:
        card.pos = float(pos)
    list_.cards.append(card)
    list_.cards.sort(key=lambda other: other.pos)
    list_.card_count = len(list_.cards)
