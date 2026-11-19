"""Config flow for Trello integration."""
from typing import Any

from trello import Member, Unauthorized
import voluptuous as vol
from voluptuous.schema_builder import Schema

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_API_TOKEN
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from . import TrelloAdapter
from .const import (
    CONF_BOARD_IDS,
    CONF_CHAINS,
    CONF_USER_EMAIL,
    CONF_USER_ID,
    DOMAIN,
    LOGGER,
)

CONF_LISTS = "lists"
CONF_ADD_ANOTHER = "add_another"

CREDS_FORM_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): str,
        vol.Required(CONF_API_TOKEN): str,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for the initial setup of a Trello integration."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self.api_key: str = ""
        self.api_token: str = ""
        self.user_email: str = ""
        self.user_id: str = ""
        self.ids_boards: dict[str, dict[str, str]] = {}
        self.trello_adapter: TrelloAdapter

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the flow that picks boards and chains of lists."""
        return OptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Prompt user for Trello API credentials."""
        return await self._show_creds_form()

    async def async_step_creds(self, user_input: dict[str, Any]) -> FlowResult:
        """Re-prompt for creds if invalid. Otherwise, prompt user for boards.

        :param user_input: api_key and api_token.
        """
        self.api_key = user_input[CONF_API_KEY]
        self.api_token = user_input[CONF_API_TOKEN]
        self.trello_adapter = TrelloAdapter.from_creds(
            user_input[CONF_API_KEY], user_input[CONF_API_TOKEN]
        )

        try:
            member = await self._get_current_member()
        except Unauthorized as ex:
            return await self._show_error_creds_form(ex)

        self.user_id = member.id
        self.user_email = member.email
        self.ids_boards = await self._fetch_all_boards()

        return await self._show_board_form(self.ids_boards)

    async def async_step_boards(self, user_input: dict[str, Any]) -> FlowResult:
        """Select desired boards to have card counts of per list.

        :param user_input: User's selected boards
        """
        board_ids = user_input[CONF_BOARD_IDS]

        await self.async_set_unique_id(self.user_id)
        self._abort_if_unique_id_configured()

        config_data: dict[str, str] = self._get_config_data()
        config_options = {CONF_BOARD_IDS: board_ids}

        return self.async_create_entry(
            title=self.user_email, data=config_data, options=config_options
        )

    def _get_config_data(self) -> dict[str, str]:
        return {
            CONF_API_KEY: self.api_key,
            CONF_API_TOKEN: self.api_token,
            CONF_USER_ID: self.user_id,
            CONF_USER_EMAIL: self.user_email,
        }

    async def _show_creds_form(self) -> FlowResult:
        return self.async_show_form(
            step_id="creds", data_schema=CREDS_FORM_SCHEMA, last_step=False
        )

    async def _show_board_form(
        self, ids_boards: dict[str, dict[str, str]]
    ) -> FlowResult:
        return self.async_show_form(
            step_id="boards",
            data_schema=_get_board_select_schema(ids_boards),
        )

    async def _show_error_creds_form(self, ex: Unauthorized) -> FlowResult:
        LOGGER.error("Unauthorized: %s)", ex)
        return self.async_show_form(
            step_id="creds",
            data_schema=CREDS_FORM_SCHEMA,
            errors={"base": "invalid_auth"},
            last_step=False,
        )

    async def _fetch_all_boards(self) -> dict[str, dict[str, str]]:
        return await self.hass.async_add_executor_job(self.trello_adapter.get_boards)

    async def _get_current_member(self) -> Member:
        return await self.hass.async_add_executor_job(self.trello_adapter.get_member)


class OptionsFlow(config_entries.OptionsFlow):
    """Pick the boards, then the chains of lists on each board.

    A chain is an ordered run of lists. Ticking a to-do item on a chained list
    moves its card to the next list of the chain. A board can have several
    chains, and a list can be in one of them at most.
    """

    def __init__(self) -> None:
        """Initialize options flow."""
        self.board_ids: list[str] = []
        self.ids_boards: dict[str, dict[str, str]] = {}
        self.board_lists: dict[str, dict[str, str]] = {}
        self.chains: dict[str, list[list[str]]] = {}
        self.board_index = 0
        self.chain_index = 0
        self.trello_adapter: TrelloAdapter

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Select the boards."""
        if user_input is None:
            data = self.config_entry.data
            self.trello_adapter = TrelloAdapter.from_creds(
                data[CONF_API_KEY], data[CONF_API_TOKEN]
            )
            self.ids_boards = await self.hass.async_add_executor_job(
                self.trello_adapter.get_boards
            )
            current = [
                board_id
                for board_id in self.config_entry.options[CONF_BOARD_IDS]
                if board_id in self.ids_boards
            ]
            return self.async_show_form(
                step_id="init",
                data_schema=_get_board_select_schema(self.ids_boards, current),
                last_step=False,
            )

        self.board_ids = user_input[CONF_BOARD_IDS]
        self.board_lists = await self.hass.async_add_executor_job(
            self.trello_adapter.get_lists, self.board_ids
        )
        return await self._show_next_chain_form()

    async def async_step_chain(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Take one chain for the current board, then ask for the next."""
        user_input = user_input or {}
        board_id = self.board_ids[self.board_index]
        list_ids: list[str] = user_input.get(CONF_LISTS, [])
        if len(list_ids) == 1:
            return self._show_chain_form(list_ids, {"base": "chain_too_short"})
        if list_ids:
            self.chains.setdefault(board_id, []).append(list_ids)

        self.chain_index += 1
        if not user_input.get(CONF_ADD_ANOTHER) or len(self._free_lists()) < 2:
            self.board_index += 1
            self.chain_index = 0
        return await self._show_next_chain_form()

    async def _show_next_chain_form(self) -> FlowResult:
        """Show the next chain form, skipping boards too small to have one."""
        while self.board_index < len(self.board_ids):
            if len(self._free_lists()) >= 2:
                return self._show_chain_form(self._previous_chain(), {})
            self.board_index += 1
            self.chain_index = 0
        return self.async_create_entry(
            data={CONF_BOARD_IDS: self.board_ids, CONF_CHAINS: self.chains}
        )

    def _show_chain_form(
        self, suggested: list[str], errors: dict[str, str]
    ) -> FlowResult:
        board_id = self.board_ids[self.board_index]
        options = [
            SelectOptionDict(value=list_id, label=name)
            for list_id, name in self._free_lists().items()
        ]
        return self.async_show_form(
            step_id="chain",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_LISTS, description={"suggested_value": suggested}
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_ADD_ANOTHER, default=self._has_later_chain()
                    ): bool,
                }
            ),
            description_placeholders={
                "board": self.ids_boards[board_id]["name"],
                "number": str(self.chain_index + 1),
            },
            errors=errors,
            last_step=False,
        )

    def _free_lists(self) -> dict[str, str]:
        """Lists of the current board not yet in one of its new chains."""
        board_id = self.board_ids[self.board_index]
        used = {id_ for chain in self.chains.get(board_id, []) for id_ in chain}
        return {
            list_id: name
            for list_id, name in self.board_lists.get(board_id, {}).items()
            if list_id not in used
        }

    def _old_chains(self) -> list[list[str]]:
        board_id = self.board_ids[self.board_index]
        return self.config_entry.options.get(CONF_CHAINS, {}).get(board_id, [])

    def _previous_chain(self) -> list[str]:
        """The chain saved earlier in this place, to start the form from."""
        old_chains = self._old_chains()
        if self.chain_index >= len(old_chains):
            return []
        free = self._free_lists()
        return [id_ for id_ in old_chains[self.chain_index] if id_ in free]

    def _has_later_chain(self) -> bool:
        return self.chain_index + 1 < len(self._old_chains())


def _get_board_select_schema(
    boards: dict[str, dict], default: list[str] | None = None
) -> Schema:
    options = {key: value["name"] for key, value in boards.items()}
    key = (
        vol.Required(CONF_BOARD_IDS)
        if default is None
        else vol.Required(CONF_BOARD_IDS, default=default)
    )
    return vol.Schema({key: cv.multi_select(options)})
