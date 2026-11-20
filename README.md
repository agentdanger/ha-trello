# ha-trello
![maintenance-status](https://img.shields.io/badge/maintenance-active-brightgreen)

Trello integration for Home Assistant. Your Trello lists become to-do lists in Home Assistant, and
ticking a card can move it along your board.

This is a fork of [ScottG489/ha-trello](https://github.com/ScottG489/ha-trello). The original gives
you a sensor with the number of cards in each list. This fork adds to-do lists, chains, moving cards,
undo, and a setting for how often Trello is checked.

## Contents
- [What you get](#what-you-get)
- [Install](#install)
- [Get a Trello API key and token](#get-a-trello-api-key-and-token)
- [Set up the integration](#set-up-the-integration)
- [To-do lists](#to-do-lists)
- [Chains](#chains)
- [Moving a card back](#moving-a-card-back)
- [How often Trello is checked](#how-often-trello-is-checked)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

## What you get
For every list on the boards you pick:

| Entity | Example | What it is |
|---|---|---|
| To-do list | `todo.house_to_do` | One item per card, with the card's name, description, and due date. |
| Sensor | `sensor.house_to_do` | The number of cards in the list. |

For every chain you define:

| Entity | Example | What it is |
|---|---|---|
| Button | `button.house_undo_last_move_to_do_doing_done` | Puts the last card moved along the chain back where it was. |

There is also one action, `trello.move_card`, for automations and scripts.

Labels, members, checklists, and attachments are not shown.

## Install
You need Home Assistant 2026.11 or newer, which installs custom integrations from
**Settings > Marketplace**.

1. In Home Assistant, open **Settings > Marketplace**.
2. Choose **Add from link** and paste `https://github.com/agentdanger/ha-trello`.
3. Install **Trello**, then restart Home Assistant.

On an older Home Assistant with HACS, add the same address
[as a custom repository](https://hacs.xyz/docs/faq/custom_repositories/) of type Integration.

To update later, install the new version from the Marketplace and restart Home Assistant.

## Get a Trello API key and token
The integration signs in to Trello with two values, an **API key** and a **token**. You create both
once, in Trello's [Power-Up Admin Portal](https://trello.com/power-ups/admin/).

1. Sign in to [Trello](https://trello.com/) in your browser.
2. Open the [Power-Up Admin Portal](https://trello.com/power-ups/admin/) and select **New** near the top right.
3. Fill in every field except **Iframe connector URL**. The name is only for you, for example "Home Assistant".
4. Select **Create**.
5. On the **API key** page, select **Generate a new API key**, and confirm if a dialog asks.
6. Copy the **API key** at the top of the page. This is the first value.
7. To the right of the API key, at the end of the paragraph, select the **Token** link ("manually generate a Token").
8. On the page that asks "Would you like to give the following application access to your account?", select **Allow**.
9. Copy the **Token** shown on the next page. This is the second value.

The token must be allowed to write (scope `read,write`), or the to-do lists can show cards but not
change them. The token link in step 7 asks for this.

Treat both values like a password. Anyone who has them can read and change your boards.

## Set up the integration
1. In Home Assistant, open **Settings > Devices & services > Add integration** and search for **Trello**,
   or use this button:

   [![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=trello)
2. Paste the **API key** and the **token**.
3. Pick the boards you want.

Each board appears as a device, with a to-do list and a sensor for each of its lists. To change the
boards, set up chains, or change how often Trello is checked, open the integration and select
**Configure**.

## To-do lists
Add a list to a dashboard with the **To-do list** card and pick one of the `todo.` entities.

| You do this in Home Assistant | This happens in Trello |
|---|---|
| Add an item | A card is added at the bottom of the list. |
| Rename an item, or change its description or due date | The card is changed. |
| Drag an item up or down | The card moves within its list. |
| Remove an item | The card is archived. Nothing is deleted. |
| Tick an item | Depends on whether the list is in a chain. See below. |

A due date set without a time is saved in Trello as 9:00 AM that day.

A Home Assistant to-do item has one checkbox, and what it does depends on the list:

- On a list that is in no chain, the checkbox is the card's own complete mark in Trello.
  Tick it and the card is marked complete; untick it and the mark is removed. The card stays in its list.
- On a list that is in a chain, the checkbox means "move this card on".

## Chains
### What a chain is
On most boards a card moves through lists from left to right as the work gets done:

```
To Do  ->  Doing  ->  Done
```

A chain tells the integration that these lists are steps of one flow, and in what order. Once it
knows that, ticking a card in To Do moves it to Doing, and ticking it there moves it to Done.

- Every card on a chained list shows unchecked, because being on the list means it is not finished
  with that step yet.
- Ticking a card moves it to the top of the next list in the chain.
- Ticking a card on the last list of the chain archives it. If you want finished cards to stay
  visible, do not tick them on the last list, or leave that list out of the chain.
- A tick never moves a card to a list outside its chain.
- A board can have more than one chain, for example `Wishes -> Bought` next to `To Do -> Doing -> Done`.
- A list can be in one chain at most. Lists you leave out of every chain, such as an "On Hold" list,
  keep the plain complete-mark checkbox.

### Set up a chain
1. Open **Settings > Devices & services > Trello** and select **Configure**.
2. Confirm your boards and select **Submit**.
3. For each board with two or more lists you see a screen titled **(board): chain 1**. In
   **Lists, in order**, pick the lists in the order a card moves through them. The order you pick
   them in is the order of the chain, so pick To Do first, then Doing, then Done.
4. To add a second chain on the same board, turn on **Add another chain for this board** before you
   submit. You are shown the lists that are still free.
5. Select **Submit**. Leave the lists empty to have no chain on a board.

A chain needs at least two lists. To change a chain later, open **Configure** again; your current
chains are filled in.

### Use a chain
Put the to-do lists of a chain next to each other on a dashboard, one **To-do list** card per list.
Tick a card in the first list and it leaves that list and appears at the top of the next one, in
Home Assistant and in Trello.

## Moving a card back
A tick only moves a card forward. There are two ways to move one back.

### The Undo last move button
Each chain has a button named **Undo last move (To Do > Doing > Done)**. Add it to a dashboard with
a **Button** card, or as a row in an **Entities** card, and pick the `button.` entity whose name
contains `undo_last_move`.

Press it and the last card moved along that chain goes back to the list and position it came from.
A card that was archived by a tick on the last list comes out of the archive.

- It remembers one move per chain. After you press it there is nothing to undo until the next move.
- It covers moves made in Home Assistant (a tick or the `trello.move_card` action), not moves made in Trello.
- The remembered move is forgotten when Home Assistant restarts or the integration is reconfigured.
- The button's `card` attribute names the card it would move back.

### The trello.move_card action
Use this in an automation, a script, or **Developer tools > Actions**. It moves a card `next` or
`previous` along its chain, or to any list on the same board by name. Target the to-do list the card
is on now.

```yaml
action: trello.move_card
target:
  entity_id: todo.house_doing
data:
  item: Paint the fence
  direction: previous
```

```yaml
action: trello.move_card
target:
  entity_id: todo.house_doing
data:
  item: Paint the fence
  list: On Hold
```

`item` is the card's name or ID. Give either `direction` or `list`, not both.

## How often Trello is checked
Changes you make in Home Assistant show at once. Changes made in Trello itself, on the website or
the app, show the next time the integration checks the board.

It checks every 15 seconds by default. To change that, open **Configure** and set
**Check Trello for changes every** to between 5 and 600 seconds.

Each check is a single request to Trello, whatever the number of cards. Trello allows
[100 requests every 10 seconds per token](https://developer.atlassian.com/cloud/trello/guides/rest-api/rate-limits/),
so even the 5-second setting uses a small part of the allowance. If you use the same token in other
tools, they share it.

## Troubleshooting
| What you see | What to do |
|---|---|
| The error "The API token needs write access." | The token can read but not write. Create a new token with the steps above and set the integration up again. |
| Ticking a card archived it. | The card was on the last list of a chain. Press that chain's **Undo last move** button, or restore the card from the archive in Trello. |
| A change made in Trello is slow to show. | Lower **Check Trello for changes every** in **Configure**. |
| A list is missing. | Check that its board is selected in **Configure**. A list added in Trello appears after the integration is reloaded. |

## Planned features
- Services for creating, updating, and deleting lists and boards.
- OAuth support ([as soon as Trello adds support for OAuth2](https://developer.atlassian.com/cloud/trello/guides/rest-api/authorization/#using-basic-oauth))
- Moving to a push model rather than polling for improved responsiveness.
- [Anything you'd like to request that this integration doesn't do!](https://github.com/agentdanger/ha-trello/issues/new?assignees=&labels=Feature%2BRequest&projects=&template=feature_request.yaml)

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
When finished, the new version can be installed from the Marketplace.
