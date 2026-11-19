# ha-trello
![maintenance-status](https://img.shields.io/badge/maintenance-active-brightgreen)

Trello integration for Home Assistant.

This is a fork of [ScottG489/ha-trello](https://github.com/ScottG489/ha-trello) that adds to-do lists, chains, and moving cards. The count sensors and the setup are the original's.

## Features
- Sensors to track the number of cards in the lists on any Trello board.
- A to-do list for each Trello list, with an item for each card: its name, description, and due date.
  Adding, editing, reordering, and removing items in Home Assistant changes the cards in Trello.
  Removing an item archives its card; nothing is deleted.
- Chains: ticking an item moves its card to the next list. See [Chains](#chains).
- A `trello.move_card` action and an "Undo last move" button for moving cards back.

Labels, members, checklists, and attachments are not shown.

### Chains
Home Assistant to-do items have one checkbox. On a Trello board, work usually moves through lists
(To Do, Doing, Done), so the checkbox can be made to mean "move this card on".

Open the integration's **Configure** dialog, pick your boards, and then for each board pick the lists
that make a chain, **in the order a card moves through them**. A board can have more than one chain,
and a list can be in one chain at most.

- On a chained list every card shows unchecked. Ticking one moves the card to the top of the next
  list of the chain. Ticking a card on the last list archives it.
- On a list that is in no chain, the checkbox is the card's own complete mark in Trello.
- Each chain has an **Undo last move** button, which puts the last card moved along that chain
  back where it was (out of the archive too). It remembers one move, and not across a restart.
- The `trello.move_card` action moves a card `next` or `previous` along its chain, or to any list on
  the same board by name:

```yaml
action: trello.move_card
target:
  entity_id: todo.my_board_doing
data:
  item: Paint the fence
  direction: previous   # or: list: To Do
```

A due date set in Home Assistant without a time is saved in Trello as 9:00 AM that day.
Changes made in Home Assistant show at once. Changes made in Trello show at the next check, every
15 seconds unless you set another interval in the **Configure** dialog (5 seconds at the least).

### Planned features
- Services for creating, updating, and deleting lists and boards.
- OAuth support ([as soon as Trello adds support for OAuth2](https://developer.atlassian.com/cloud/trello/guides/rest-api/authorization/#using-basic-oauth))
- Moving to a push model rather than polling for improved responsiveness.
- [Anything you'd like to request that this integration doesn't do!](https://github.com/agentdanger/ha-trello/issues/new?assignees=&labels=Feature%2BRequest&projects=&template=feature_request.yaml)



## Installation
First add this repository [as a custom repository](https://hacs.xyz/docs/faq/custom_repositories/).

### Setup
#### Prerequisites

Before setting up this integration, you need to get credentials by creating an Integration in Trello's
[Power-Up Admin Portal](https://trello.com/power-ups/admin/).

<details>
<summary><strong>Create Integration and associated API key and Token</strong></summary>

1. Ensure you're logged in to [Trello](https://trello.com/) in your browser.
2. Visit the [Power-Up Admin Portal](https://trello.com/power-ups/admin/) and select **New** near the top right.
3. Fill out all fields except the **Iframe connector URL**.
4. Select **Create** near the bottom right.
5. You should be taken to the **API key** page. Select **Generate a new API key** and select **Generate API key** if a
   dialog pops up.
6. Record the **API key** at the top of the page. *This will be the first of two credentials you'll need.*
7. At the end of the paragraph to the right of your **API key**, select the **Token** link to "... manually generate a Token."
8. You should be taken to a page with text at the top saying **"Would you like to give the following application access to your account?"**.
   Select the **"Allow"** button near the bottom right of the page.
9. On the following page, record your **Token**. *This will be the last credential you'll need.*
</details>

The token must allow writing (scope `read,write`) for the to-do lists to change cards.

After you have both your **API Key** and **Token** you can start the integration setup.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=trello)

## Development
Run the following to set up your development environment
```shell
python3 -m venv venv
source venv/bin/activate
pip3 install -r requirements_test.txt
```
To run Home Assistant with this integration loaded:
```shell
hass -c config
```
### Testing
To run unit tests with coverage:
```shell
pytest tests --cov=custom_components.trello --cov-report term-missing
```

### Releasing
[Create a new GitHub release](https://github.com/agentdanger/ha-trello/releases/new). The [release workflow](https://github.com/agentdanger/ha-trello/blob/master/.github/workflows/release.yaml) takes care of the rest.
When finished, it will be available to download via HACS.

### Troubleshooting
Ensure pip is at the latest version:
`pip3 install -r requirements_test.txt`
