"""Test the trello options flow: boards, then chains of lists per board."""
from unittest.mock import patch

from custom_components.trello.const import CONF_BOARD_IDS, CONF_CHAINS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from pytest_homeassistant_custom_component.common import MockConfigEntry

GOALS = "goals_id"
IDEAS = "ideas_id"


class MockAdapter:
    """Mock TrelloAdapter."""

    @classmethod
    def from_creds(cls, api_key: str, api_token: str):
        """Init mock TrelloAdapter."""
        return cls()

    def get_boards(self):
        """Mock board dict."""
        return {
            GOALS: {"id": GOALS, "name": "Goals"},
            IDEAS: {"id": IDEAS, "name": "Ideas"},
        }

    def get_lists(self, board_ids):
        """Mock lists per board. Ideas has one list, too few for a chain."""
        lists = {
            GOALS: {"a": "To Do", "b": "Doing", "c": "Done", "d": "Wishes", "e": "Got"},
            IDEAS: {"z": "Planned"},
        }
        return {board_id: lists[board_id] for board_id in board_ids}


async def test_options_flow_chains(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Two chains on one board, kept in the order the lists were picked."""
    config_entry.add_to_hass(hass)

    with patch("custom_components.trello.config_flow.TrelloAdapter", MockAdapter):
        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "init"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_BOARD_IDS: [GOALS, IDEAS]}
        )
        assert result["step_id"] == "chain"
        assert result["description_placeholders"] == {"board": "Goals", "number": "1"}

        # One list is not a chain.
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"lists": ["a"], "add_another": True}
        )
        assert result["step_id"] == "chain"
        assert result["errors"] == {"base": "chain_too_short"}

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"lists": ["c", "b", "a"], "add_another": True}
        )
        assert result["step_id"] == "chain"
        assert result["description_placeholders"]["number"] == "2"

        # Only two lists are left, so there is no third chain to ask about,
        # and Ideas has too few lists to be asked about at all.
        with patch("custom_components.trello.async_setup_entry", return_value=True):
            result = await hass.config_entries.options.async_configure(
                result["flow_id"], {"lists": ["d", "e"], "add_another": True}
            )
            await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        CONF_BOARD_IDS: [GOALS, IDEAS],
        CONF_CHAINS: {GOALS: [["c", "b", "a"], ["d", "e"]]},
    }
