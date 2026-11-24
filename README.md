# Discord integration for Flow Steward

<img src="icon.png" width="96" alt="Discord integration for Flow Steward">

[![CI](https://img.shields.io/github/actions/workflow/status/Flow-Steward/ext-messaging-discord/ci.yml?branch=main&label=CI)](https://github.com/Flow-Steward/ext-messaging-discord/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/Flow-Steward/ext-messaging-discord?label=release)](https://github.com/Flow-Steward/ext-messaging-discord/releases/latest)
[![Discord API](https://img.shields.io/badge/Discord%20API-v10-5865F2)](https://discord.com/developers/docs/reference)
[![Steps](https://img.shields.io/badge/steps-264-blue)](docs/API-COVERAGE.md)

Automate Discord with Flow Steward workflows and AI agents — no code, no bot hosting. Post messages, embeds and files to channels, read whole message histories and member lists, run moderation, manage roles, threads, webhooks and scheduled events, and keep your Discord server in step with the rest of your business systems.

Every operation of the Discord REST API v10 is a ready-made workflow step: 258 Discord steps, each with its own form and Discord's own description, plus everyday steps for the common jobs.

## What is this

[Discord](https://discord.com) is where communities, customers and teams talk: in servers, channels, threads and direct messages. [Flow Steward](https://docs.flowsteward.org) runs workflows and AI agents that connect business systems.

This extension is the connector between the two. Once installed, Discord appears in the Flow Steward workflow editor as a set of steps, and the same operations are available to AI agents as tools. A step can act:

- **as your Discord bot** — the usual case: the bot posts, reads, moderates and manages, with the permissions of its role in each server;
- **for a Discord user** with that user's OAuth2 token — their servers, connections, entitlements, or adding them to a server;
- **through a webhook** — posting to one channel without any bot at all.

You do not host a bot process. Flow Steward calls Discord when a workflow step runs, with the token stored in the project connection.

## What you can automate

### Notifications and announcements

- **Operations alerts.** When a job fails, a server is down or a payment is refused in another system, post a message with the details to an on-call channel, with an embed and a link back to the source.
- **Release notes and product announcements.** When a release is published, post the changelog to an announcement channel and **crosspost** it to every server that follows the channel.
- **Daily and weekly reports.** On a schedule, collect numbers from your CRM, shop or analytics and post a formatted summary — or attach the full CSV or PDF produced by an earlier step.
- **Webhook posting without a bot.** Send build results, form submissions or monitoring events to a channel through a channel webhook, with a custom name and avatar per message.

### Community and server management

- **Onboarding roles.** When someone buys a product, joins a course or signs a contract, give them the matching role on your server — and remove it when the subscription ends.
- **Channels and threads for each project.** Create a private channel or a thread for every new customer, deal or ticket, set its permission overwrites, and archive it when the work is done.
- **Scheduled events.** Create Discord events for webinars, streams and meetups from your calendar or CRM, update them when plans change, and read who is interested.
- **Invites.** Create invite links with an expiry and a use limit for each campaign, and list or revoke them later.
- **Emojis, stickers and sounds.** Upload a new emoji or sticker from a workflow file, or keep a soundboard in step with a brand kit.

### Moderation and safety

- **Moderation reports.** Read the server's audit log on a schedule and send a summary of bans, kicks and role changes to the moderators' channel.
- **Ban and timeout workflows.** Ban or unban users, bulk-ban a list of accounts, time members out, or prune inactive members — with an audit log reason on every change.
- **Auto moderation rules.** Create and update Discord's auto moderation rules from a reviewed list of blocked words or links.
- **Join requests.** Read pending join requests of a server and approve or reject them by your own criteria.

### Data and AI

- **Whole histories for AI agents.** Read every message of a channel page after page, and let an AI agent summarise a discussion, extract decisions or answer questions about it.
- **Member exports.** Read every member of a server — names, roles, join dates — for a CRM sync or an engagement report.
- **Search.** Search messages in a server by author, channel, content type or mentions, and pass the results on.
- **Polls.** Read who voted for each answer of a poll, or end a poll early.

### Applications and monetization

- **Slash commands as code.** Create, update and order your application's global and per-server slash commands from a definition kept in Git.
- **Entitlements and SKUs.** Read the SKUs and subscriptions of your application, grant test entitlements, or consume a one-time purchase after delivering it.
- **Discord Social SDK.** Create lobbies, send lobby messages and manage application identities for games and apps built with the Discord Social SDK.

## Why teams use it

- **The whole Discord REST API, step by step.** 258 Discord steps: the 250 operations of the pinned Discord API description and eight more from Discord's API documentation. Each step carries Discord's own name and description, and each input a label and help text.
- **Everyday steps for the common jobs.** Send a message, read a channel or a server, list messages and channels — with the fewest inputs possible.
- **Whole lists, not a first page.** List steps read page after page with `all_pages`. If the step's time or output is used up, the result says so: `complete` is false and `next_cursor` tells the next run where to continue.
- **Files from the workflow.** Attach files of up to 20 MiB each — Discord's default upload limit per file — produced by earlier steps, or small files as base64. The part's Content-Type follows the file name.
- **Changes are sent once.** A step that changes data is never retried automatically. If Discord's answer is lost after a change was sent, the step says that the outcome is unknown instead of guessing; message creation carries a nonce so Discord can recognise a repeated send.
- **Test runs change nothing.** Every change is a declared external effect: in a test run the step checks its inputs and sends nothing to Discord.
- **Answers are read whole.** An answer that is cut off, too large or not the documented JSON is an error, never an empty result.
- **Rate limits in plain sight.** Every step returns Discord's rate limit headers (`limit`, `remaining`, `reset_after`, `bucket`, `global`); when Discord asks to wait, the step returns how long.
- **Tokens stay secret.** Bot, OAuth2 and webhook tokens live only in the project connection, encrypted; tokens in Discord's answers are removed before any workflow sees them.

## What's inside

### Everyday steps

- **Test connection** — checks the bot token by reading the bot's own user.
- **Send message** — posts a text message to a channel as the bot; mentions in the text notify nobody.
- **Get channel** — reads a channel by its ID.
- **List channel messages** — reads a channel's messages, newest first; with `all_pages` the whole history.
- **Get server** — reads a server, with approximate member counts when asked.
- **List server channels** — reads every channel of a server.

### Discord API steps by group

- **Messages** (23 steps) — create, edit, delete and bulk-delete messages, reactions, pins, polls, crossposting and message search. Examples: **Create Message**, **Bulk Delete Messages**, **Create Reaction**, **Get Answer Voters**.
- **Channels and threads** (39 steps) — channels, threads and their members, permission overwrites, invites, stage instances and the typing indicator. Examples: **Modify Channel**, **Start Thread without Message**, **Edit Channel Permissions**, **Create Channel Invite**.
- **Servers and members** (42 steps) — servers, members and nicknames, onboarding, welcome screen, widgets, templates, integrations and voice states. Examples: **List Guild Members**, **Search Guild Members**, **Modify Guild Member**, **Modify Guild Onboarding**.
- **Roles** (9 steps) — create, change, order and delete roles, and give them to members. Examples: **Create Guild Role**, **Add Guild Member Role**, **Modify Guild Role Positions**.
- **Moderation and audit log** (17 steps) — bans and bulk bans, pruning, join requests, auto moderation rules and the audit log. Examples: **Get Guild Audit Log**, **Create Guild Ban**, **Begin Guild Prune**, **Create Auto Moderation Rule**.
- **Webhooks** (18 steps) — create and change webhooks, post through them (also in Slack- and GitHub-compatible form) and edit their messages. Examples: **Create Webhook**, **Execute Webhook**, **Edit Webhook Message**.
- **Emojis, stickers and sounds** (25 steps) — server and application emojis, stickers and sticker packs, soundboard sounds. Examples: **Create Guild Emoji**, **Create Guild Sticker**, **Send Soundboard Sound**.
- **Scheduled events** (11 steps) — create and change events and their exceptions, and read their subscribers. Examples: **Create Guild Scheduled Event**, **Get Guild Scheduled Event Users**.
- **Applications, commands and interactions** (31 steps) — the application, its global and server slash commands and their permissions, role connection metadata, interaction responses and the Gateway address. Examples: **Bulk Overwrite Global Application Commands**, **Edit Application Command Permissions**, **Create Interaction Response**.
- **Lobbies and Social SDK** (23 steps) — lobbies and their members and messages, provisional accounts and application identities of the Discord Social SDK. Examples: **Create Lobby**, **Send Lobby Message**.
- **Monetization** (9 steps) — SKUs, entitlements and subscriptions. Examples: **List SKUs**, **List Entitlements**, **Consume an Entitlement**.
- **Users and OAuth2** (11 steps) — the current user, their servers, connections and DMs, and OAuth2 information. Examples: **Get Current User Guilds**, **Create DM**, **Get Current User Connections**.

The full list — every step, the Discord endpoint it calls, its inputs, the fields of its request body and the fields Discord returns — is on the **Discord API coverage** page of the installed extension and in [docs/API-COVERAGE.md](docs/API-COVERAGE.md).

### Pages in Flow Steward

- **Setup Guide** — create the bot, turn on intents, add it to your server, find IDs.
- **Connection**, **OAuth2 connection**, **Webhook connection** — one page per connection type, with its form and when to use it.
- **Discord API** and one page per group — every step with what it does.
- **Discord API coverage**, **Changelog**, **Support**.

## Get started

1. **Install the extension.** In Flow Steward open **Extensions → Catalog**, find **Discord** and install it.
2. **Create a bot.** In the [Discord Developer Portal](https://discord.com/developers/applications) press **New Application**, open **Bot**, press **Reset Token** and copy the token.
3. **Turn on the intents your steps need** under **Privileged Gateway Intents**: **Server Members Intent** for member lists, **Message Content Intent** to read message text.
4. **Add the bot to your server.** In **OAuth2 → URL Generator** tick the scope `bot` and the permissions your steps need, open the link and choose the server.
5. **Connect it.** On the extension's **Connection** page paste the token, save, and press **Test connection**.
6. **Build your first workflow.** For example: *on a schedule* → *your report step* → **Send message** with the channel ID. Turn on Discord's **Developer Mode** (User Settings → Advanced) to copy IDs with a right-click.

## Requirements

- **A Flow Steward host** that runs extensions with the extension host contract v2.
- **A Discord application with a bot**, added to the servers the workflows use.
- **Permissions of the bot's role** for the steps you run, for example **View Channels**, **Send Messages**, **Read Message History**, **Attach Files**, **Manage Messages**, **Manage Channels**, **Manage Roles**, **Manage Webhooks**, **Ban Members**, **View Audit Log** or **Manage Events**. Discord names the permission each endpoint needs.
- **Role order.** Discord lets a bot grant, edit and sort only roles below its own highest role, and kick, ban or rename only members whose highest role is below it.
- **Privileged intents.** Member lists need the **Server Members Intent**; message text, embeds, attachments and components are returned only with the **Message Content Intent**.
- **Other connections where a step needs them.** Steps that act for a person take a user's OAuth2 token (**Discord OAuth2 token** connection); steps addressed by a webhook or interaction token take it from a **Discord webhook or interaction token** connection.
- **Sizes.** Discord accepts files of up to 20 MiB each by default and up to ten files per request. A Discord answer is read up to 8 MiB, and a step's whole result stays within 3,500,000 bytes.

## FAQ

**How do I post a Discord message from a workflow?**
Add **Send message**, choose the Discord bot connection, enter the channel ID and the text. For embeds, components, polls or files, use **Create Message** and put the message in `body` as `{"data": {"content": "...", "embeds": [...]}}`.

**How do I send a file produced by another step?**
In **Create Message**, set the body format to `multipart/form-data`, put the message in `body`, and add the file to **Workflow files** with the field `files[0]` and a file name such as `report.pdf`.

**Can I post without creating a bot?**
Yes. Create a webhook in the channel's settings, save its token in a **Discord webhook or interaction token** connection, and use **Execute Webhook** with the webhook's ID.

**How do I read every member of a server?**
Turn on the **Server Members Intent** for the bot, then run **List Guild Members** with **All pages** on. If the result says `complete: false`, run it again with `after` set to `next_cursor`.

**Why are message texts empty?**
Discord returns message content, embeds, attachments and components only to applications with the **Message Content Intent**. Turn it on in the Developer Portal.

**Why is a role change refused?**
The bot's own highest role must be above the role it gives or edits. Drag the bot's role higher in **Server Settings → Roles**.

**What happens if a send times out?**
The step reports `timeout_unknown`: Discord may have posted the message. The step does not send it again by itself; look at the channel before running the step again.

**Can a workflow answer slash commands and buttons?**
Discord delivers interactions to the application's own endpoint and expects the first answer within 3 seconds. If your service receives the interaction and answers it, workflow steps can then send followups with the interaction token through the webhook steps, and edit or delete the original response. Live events reach applications over Discord's Gateway connection.

**Does a test run post anything?**
No. In a test run every step that changes data checks its inputs and sends nothing.

**Where is the full list of operations?**
On the **Discord API coverage** page of the installed extension, and in [docs/API-COVERAGE.md](docs/API-COVERAGE.md).

## In your language

**Русский.** Интеграция Discord для Flow Steward автоматизирует Discord без программирования и без своего сервера для бота: отправляет сообщения, вложения и файлы в каналы, читает всю историю канала и всех участников сервера, ведёт модерацию, управляет ролями, ветками, вебхуками и событиями. Каждая из 258 операций Discord REST API v10 — готовый шаг workflow со своим описанием, плюс шаги для повседневных задач.

**Deutsch.** Die Discord-Integration für Flow Steward automatisiert Discord ohne Programmierung: Nachrichten und Dateien in Kanäle senden, ganze Nachrichtenverläufe und Mitgliederlisten lesen, moderieren sowie Rollen, Threads, Webhooks und Events verwalten. Jede der 258 Operationen der Discord REST API v10 ist ein eigener Workflow-Schritt.

**Español.** La integración de Discord para Flow Steward automatiza Discord sin programar: publica mensajes y archivos en canales, lee historiales completos y listas de miembros, modera y gestiona roles, hilos, webhooks y eventos. Cada una de las 258 operaciones de la API REST v10 de Discord es un paso de workflow propio.

**Français.** L'intégration Discord pour Flow Steward automatise Discord sans code : publier des messages et des fichiers dans les salons, lire des historiques complets et des listes de membres, modérer et gérer rôles, fils, webhooks et événements. Chacune des 258 opérations de l'API REST v10 de Discord est une étape de workflow à part entière.

## Links

- Flow Steward documentation: <https://docs.flowsteward.org>
- Flow Steward extension catalog: <https://github.com/Flow-Steward/extensions>
- Issues and support: <https://github.com/Flow-Steward/ext-messaging-discord/issues>
- Discord developer documentation: <https://discord.com/developers/docs/reference>
- Discord Developer Portal: <https://discord.com/developers/applications>
- Changes: [CHANGELOG.md](CHANGELOG.md)

## For developers

The steps are generated from pinned sources:

- the Discord OpenAPI description, discord-api-spec `3a21a01` (`tests/reference/discord-openapi.json`);
- routes documented only in discord-api-docs `9b737ec` (`tests/reference/discord-docs-routes.json`);
- each endpoint's name, first paragraph and parameter descriptions from discord-api-docs `9b737ec`, extracted by `tests/reference/extract_endpoint_docs.py` into `tests/reference/discord-endpoint-docs.json` with the SHA-256 of every page read.

```bash
python3 scripts/build_rest_registry.py
python3 scripts/build_actions.py
python3 scripts/build_pages.py
```

`scripts/step_docs.py` holds the step groups and the one description each input name has in every step. The tests fail when a generated file or page drifts from its generator.

From a Flow Steward checkout (the checks run in the `fs-audit` container):

```bash
./core/entrypoints/cli/scripts/lint.sh --checks extension-static,extension-tests --extension-root "$PWD/workspace/extensions/flowsteward_discord"
./flow-steward extensions validate flowsteward.discord --root workspace/extensions --health --marketplace
./flow-steward extensions test flowsteward.discord --root workspace/extensions
```

`tests/test_live.py` reads real data from Discord (GET requests only) when `DISCORD_TOKEN_FILE` names a file with a bot token, and is skipped otherwise.

Discord and its marks belong to Discord Inc.; see [BRANDING.md](BRANDING.md) for the icon's source.
