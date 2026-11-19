"""Test the trello to-do lists, chains, undo button, and move service."""
from collections.abc import Generator
from unittest.mock import patch

import pytest

from custom_components.trello.const import CONF_CHAINS, DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from pytest_homeassistant_custom_component.common import MockConfigEntry
from .conftest import ComponentSetup, mock_fetch_json

GOALS = "3a634d47a4cb1e9a9886a2e3"
TO_DO = "c46d44769cdac5020be265db"
DONE = "07414c5aa9758dcb06022a73"
MARATHON = "e091455385887f18fee685ab"
BOOKS = "a48b45008848cc7998b4f3e0"
SHED = "282344a3919cb5f3e0dbc5a4"

UNDO_BUTTON = "button.goals_undo_last_move_to_do_done"


class FakeTrello:
    """Stands in for the Trello API: serves the fixture and records writes."""

    def __init__(self) -> None:
        """Start with no writes."""
        self.writes: list[tuple[str, str, dict]] = []

    def fetch_json(
        self, uri_path, http_method="GET", query_params=None, post_args=None, **_
    ):
        """Record anything that is not the batch read."""
        if uri_path == "batch":
            return mock_fetch_json("batch.json")
        self.writes.append((http_method, uri_path, post_args))
        return {}


@pytest.fixture(name="trello")
def mock_trello() -> Generator[FakeTrello, None, None]:
    """Replace the Trello client's one way out for the whole test."""
    fake = FakeTrello()
    with patch(
        "custom_components.trello.TrelloClient.fetch_json", side_effect=fake.fetch_json
    ):
        yield fake


@pytest.fixture(name="chained")
def mock_chained(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    setup_integration: ComponentSetup,
) -> None:
    """Make To Do > Done a chain on the Goals board."""
    hass.config_entries.async_update_entry(
        config_entry,
        options={**config_entry.options, CONF_CHAINS: {GOALS: [[TO_DO, DONE]]}},
    )


async def _update_item(hass: HomeAssistant, entity_id: str, **data) -> None:
    await hass.services.async_call(
        "todo", "update_item", data, target={"entity_id": entity_id}, blocking=True
    )


async def _move_card(hass: HomeAssistant, entity_id: str, **data) -> None:
    await hass.services.async_call(
        DOMAIN, "move_card", data, target={"entity_id": entity_id}, blocking=True
    )


async def test_cards_are_items(
    hass: HomeAssistant, setup_integration: ComponentSetup, trello: FakeTrello
) -> None:
    """Each list is a to-do list and each card an item, top to bottom."""
    await setup_integration()

    assert hass.states.get("todo.goals_to_do").state == "2"
    assert hass.states.get("todo.goals_done").state == "0"
    assert hass.states.get("todo.ideas_planned").state == "1"

    response = await hass.services.async_call(
        "todo",
        "get_items",
        {},
        target={"entity_id": "todo.goals_to_do"},
        blocking=True,
        return_response=True,
    )
    items = response["todo.goals_to_do"]["items"]
    assert [item["summary"] for item in items] == ["Run a marathon", "Read ten books"]
    assert items[0]["uid"] == MARATHON
    assert items[0]["description"] == "26.2 miles"
    assert items[0]["status"] == "needs_action"
    assert items[0]["due"].startswith("2026-12-01T")
    assert "due" not in items[1]


async def test_tick_on_chain_moves_card_and_undo_moves_it_back(
    hass: HomeAssistant,
    chained: None,
    setup_integration: ComponentSetup,
    trello: FakeTrello,
) -> None:
    """Ticking on a chained list moves the card to the top of the next list."""
    await setup_integration()

    await _update_item(hass, "todo.goals_to_do", item="Run a marathon", status="completed")

    assert trello.writes == [
        ("PUT", f"/cards/{MARATHON}", {"idList": DONE, "pos": "top"})
    ]
    assert hass.states.get(UNDO_BUTTON).attributes["card"] == "Run a marathon"
    # The lists show the move at once, though Trello still serves the old board.
    assert hass.states.get("todo.goals_to_do").state == "1"
    assert hass.states.get("todo.goals_done").state == "1"
    assert hass.states.get("sensor.goals_done").state == "1"

    await hass.services.async_call(
        "button", "press", {}, target={"entity_id": UNDO_BUTTON}, blocking=True
    )

    assert trello.writes[1] == (
        "PUT",
        f"/cards/{MARATHON}",
        {"idList": TO_DO, "pos": 100},
    )
    assert hass.states.get("todo.goals_to_do").state == "2"
    assert hass.states.get("todo.goals_done").state == "0"
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {}, target={"entity_id": UNDO_BUTTON}, blocking=True
        )


async def test_tick_on_standalone_list_marks_complete(
    hass: HomeAssistant,
    chained: None,
    setup_integration: ComponentSetup,
    trello: FakeTrello,
) -> None:
    """Ticking on a list in no chain sets the card's own complete mark."""
    await setup_integration()

    await _update_item(hass, "todo.ideas_planned", item="Build a shed", status="completed")

    assert trello.writes == [("PUT", f"/cards/{SHED}", {"dueComplete": True})]


async def test_edit_add_remove_and_reorder(
    hass: HomeAssistant, setup_integration: ComponentSetup, trello: FakeTrello
) -> None:
    """Changes made to items in Home Assistant are written to the cards."""
    await setup_integration()
    target = {"entity_id": "todo.goals_to_do"}

    await _update_item(
        hass,
        "todo.goals_to_do",
        item="Read ten books",
        rename="Read twelve books",
        description="One a month",
        due_datetime="2026-12-31T18:00:00+00:00",
    )
    assert trello.writes.pop() == (
        "PUT",
        f"/cards/{BOOKS}",
        {
            "name": "Read twelve books",
            "desc": "One a month",
            "due": "2026-12-31T18:00:00+00:00",
        },
    )

    await hass.services.async_call(
        "todo", "add_item", {"item": "Learn to juggle"}, target=target, blocking=True
    )
    assert trello.writes.pop() == (
        "POST",
        "/cards",
        {"idList": TO_DO, "pos": "bottom", "name": "Learn to juggle"},
    )

    await hass.services.async_call(
        "todo", "remove_item", {"item": "Run a marathon"}, target=target, blocking=True
    )
    assert trello.writes.pop() == ("PUT", f"/cards/{MARATHON}", {"closed": True})

    entity = hass.data["todo"].get_entity("todo.goals_to_do")
    await entity.async_move_todo_item(MARATHON, BOOKS)
    assert trello.writes.pop() == ("PUT", f"/cards/{MARATHON}", {"pos": "bottom"})
    await entity.async_move_todo_item(BOOKS, None)
    assert trello.writes.pop() == ("PUT", f"/cards/{BOOKS}", {"pos": "top"})


async def test_move_card_service(
    hass: HomeAssistant,
    chained: None,
    setup_integration: ComponentSetup,
    trello: FakeTrello,
) -> None:
    """The service moves a card along its chain or to a named list."""
    await setup_integration()

    await _move_card(hass, "todo.goals_to_do", item="Run a marathon", direction="next")
    assert trello.writes.pop() == (
        "PUT",
        f"/cards/{MARATHON}",
        {"idList": DONE, "pos": "top"},
    )

    await _move_card(hass, "todo.goals_to_do", item=BOOKS, list="done")
    assert trello.writes.pop() == (
        "PUT",
        f"/cards/{BOOKS}",
        {"idList": DONE, "pos": "top"},
    )

    # Nothing comes before the first list of a chain.
    with pytest.raises(HomeAssistantError):
        await _move_card(
            hass, "todo.goals_to_do", item="Run a marathon", direction="previous"
        )
    # A list in no chain has no next list.
    with pytest.raises(ServiceValidationError):
        await _move_card(hass, "todo.ideas_planned", item="Build a shed", direction="next")
    # One of direction or list, not both and not neither.
    with pytest.raises(ServiceValidationError):
        await _move_card(hass, "todo.goals_to_do", item="Run a marathon")
    assert trello.writes == []


async def test_tick_on_last_list_of_chain_archives(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    setup_integration: ComponentSetup,
    trello: FakeTrello,
) -> None:
    """Ticking on the last list of a chain archives the card; undo restores it."""
    hass.config_entries.async_update_entry(
        config_entry,
        options={**config_entry.options, CONF_CHAINS: {GOALS: [[DONE, TO_DO]]}},
    )
    await setup_integration()

    await _update_item(hass, "todo.goals_to_do", item="Run a marathon", status="completed")
    assert trello.writes.pop() == ("PUT", f"/cards/{MARATHON}", {"closed": True})

    await hass.services.async_call(
        "button",
        "press",
        {},
        target={"entity_id": "button.goals_undo_last_move_done_to_do"},
        blocking=True,
    )
    assert trello.writes.pop() == (
        "PUT",
        f"/cards/{MARATHON}",
        {"idList": TO_DO, "pos": 100, "closed": False},
    )
