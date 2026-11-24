# Discord integration for Flow Steward

<img src="icon.png" width="96" alt="Discord integration for Flow Steward">

[![CI](https://img.shields.io/github/actions/workflow/status/Flow-Steward/ext-messaging-discord/ci.yml?branch=main&label=CI)](https://github.com/Flow-Steward/ext-messaging-discord/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/Flow-Steward/ext-messaging-discord?label=release)](https://github.com/Flow-Steward/ext-messaging-discord/releases/latest)

Automate Discord with Flow Steward workflows and AI agents: post messages and files to channels, read whole message histories and member lists, manage servers, roles, threads and webhooks — without writing code.

This Flow Steward extension is a Discord integration built on the Discord REST API v10. Every operation of the pinned Discord API description has its own workflow step, and a few everyday steps cover the common tasks.

## What is this

Discord is a chat platform where communities and teams talk in servers, channels and threads. This extension is a connector: it adds Discord steps to the Flow Steward workflow editor and the same operations as tools for AI agents. A step acts as your Discord bot, as a scoped OAuth2 token or through a webhook. Read more about Flow Steward at <https://docs.flowsteward.org>.

## What you can automate

- Post a message to a channel when something happens in another system: a new order, a failed job, a report that is ready.
- Attach files from earlier workflow steps to a message: a chart, a CSV export, a PDF.
- Read the whole history of a channel, every member of a server or every ban, page after page, and pass it to an AI agent or a spreadsheet.
- Create and archive threads, pin messages, add reactions.
- Manage roles, channels, invites, scheduled events, stickers and emojis of a server.
- Read the audit log of a server for moderation reports.
- Send messages through a channel webhook without a bot.

## Why teams use it

- **The whole REST API is covered.** 258 Discord steps: the 250 operations of the pinned Discord API description and eight more from Discord's API documentation, each with its own form, plus six everyday steps. Outside this version: receiving interactions (commands, buttons) and answering them within 3 seconds with the event's token, the Gateway and Voice.
- **Whole lists, not a first page.** List steps with Discord cursors read page after page when `all_pages` is on. A list that stops early because of the step's time or output size says so: `complete` is false and `next_cursor` tells where to continue.
- **An answer that cannot be read is an error.** A read whose answer is cut off, too large or not the documented JSON fails with `invalid_response` or `response_too_large`; it never returns an empty result instead.
- **A change is sent once.** Writes are never retried automatically. If Discord's answer is lost after a write was sent, the step reports that the outcome is unknown instead of guessing. Messages carry a nonce so Discord can recognise a repeated send.
- **A test run changes nothing.** Every write is a declared external effect; a test run checks the inputs and sends nothing.
- **Discord's rate limits are visible.** Every step returns `rate_limit` from Discord's headers (limit, remaining, reset_after, bucket, global); an HTTP 429 answer returns `retry_after_seconds` and whether the limit is global.
- **Tokens stay secret.** Bot, OAuth2 and webhook tokens come only from the project connection, and tokens in Discord's answers are removed before a workflow sees them.

## What's inside

Everyday steps:

- **Test connection** — reads the bot's identity.
- **Send message** — posts a text message to a channel without notifying mentions.
- **Get channel**, **Get server** — read one channel or server.
- **List channel messages** — one page of messages, or all of them with `all_pages`.
- **List server channels** — every channel of a server.

Discord REST steps: one step for each of the 258 operations, named after the operation, for example **List guild members**, **Create message**, **Create guild role** or **Execute webhook**. Steps that send files take workflow files (`file_artifacts`) or small files as base64 (`files`); the part's Content-Type follows the file name's extension. The list of operations, with their methods and paths, is in [docs/API-COVERAGE.md](docs/API-COVERAGE.md).

## Get started

1. In Flow Steward, open **Extensions → Catalog**, find **Discord** and install it.
2. Create an application with a bot in the [Discord Developer Portal](https://discord.com/developers/applications) and copy the bot token.
3. Invite the bot to your server and give it the permissions your steps need, for example **View Channel** and **Send Messages** in the channel it posts to.
4. In Flow Steward, create a **Discord bot** project connection, paste the token and press **Test connection**.
5. Build your first workflow: for example, on a schedule → your report step → **Send message** with the channel ID (Discord's Developer Mode lets you copy it).

## Requirements

- A Discord application with a bot user, installed in the servers the workflows use, with the permissions of the steps you run.
- Many operations need Discord permissions such as **Manage Messages**, **Manage Roles** or **View Audit Log**; Discord's documentation names them for each operation.
- Steps that act for a Discord user need a **Discord OAuth2 token** connection with a token issued with the right scopes. Steps whose Discord path contains a webhook or interaction token take it from a **Discord webhook or interaction token** connection. Interaction responses go through such a connection holding the interaction token, which Discord keeps valid for 15 minutes.
- Each uploaded file is at most 20 MiB, Discord's default upload limit per file, and a request carries at most ten files; base64 files in `files` share the step input limit, so larger files go in `file_artifacts` as workflow files. A Discord answer is read up to 8 MiB, and a step's whole result stays within 3,500,000 bytes.
- Discord limits request rates per route and globally; a step that is rate limited fails with `rate_limited` and says how long to wait.
- A Flow Steward host with the extension host contract v2.

## FAQ

**How do I post a Discord message from a workflow?**
Add **Send message**, choose the Discord bot connection, enter the channel ID and the text. For embeds, components or files, use **Create message**.

**How do I send a file produced by another step?**
In **Create message**, set the media type to `multipart/form-data`, put the message in `body` and add the file to `file_artifacts` with the field `files[0]` and a file name.

**How do I read all members of a server?**
Run **List guild members** with `all_pages` on. When `complete` is false, run it again with `after` set to `next_cursor`.

**What happens if a send times out?**
The step reports `timeout_unknown`: Discord may have posted the message. It is not sent again automatically; check the channel before running the step again.

**Which Discord API operations are supported?**
All 250 operations of the Discord API description the release is pinned to, eight operations documented only in Discord's API documentation, and the six everyday steps. Not in this version: receiving interactions and their first answer, which Discord expects within 3 seconds with the token of the event ([Receiving and Responding](https://github.com/discord/discord-api-docs/blob/9b737ec51ee8d5076af0565d209a9adf8f590a27/developers/interactions/receiving-and-responding.mdx)), the Gateway (real-time events) and Voice. Discord has disabled one of them (batch editing of command permissions); its step reports `operation_disabled` without calling Discord.

## In your language

Интеграция Discord с Flow Steward автоматизирует Discord без программирования: отправляет сообщения и файлы в каналы, читает всю историю канала и всех участников сервера постранично, управляет ролями, каналами, ветками и вебхуками. Каждая из 258 операций Discord REST API v10 доступна как отдельный шаг workflow. Приём взаимодействий (команд и кнопок) с ответом в течение 3 секунд, Gateway и Voice в эту версию не входят. Для подключения нужен бот Discord и его токен.

## Links

- Flow Steward documentation: <https://docs.flowsteward.org>
- Flow Steward extension catalog: <https://github.com/Flow-Steward/extensions>
- Issues and support: <https://github.com/Flow-Steward/ext-messaging-discord/issues>
- Discord API documentation: <https://discord.com/developers/docs/reference>
- Changes: [CHANGELOG.md](CHANGELOG.md)

## For developers

The steps are generated from the pinned Discord OpenAPI description (`tests/reference/discord-openapi.json`, discord-api-spec `3a21a01`) and the documentation routes in `tests/reference/discord-docs-routes.json` (discord-api-docs `9b737ec`):

```bash
python3 scripts/build_rest_registry.py
python3 scripts/build_actions.py
```

From a Flow Steward checkout (the checks run in the `fs-audit` container):

```bash
./core/entrypoints/cli/scripts/lint.sh --checks extension-static,extension-tests --extension-root "$PWD/workspace/extensions/flowsteward_discord"
./flow-steward extensions validate flowsteward.discord --root workspace/extensions --health --marketplace
./flow-steward extensions test flowsteward.discord --root workspace/extensions
```

`tests/test_live.py` reads real data from Discord (GET requests only) when `DISCORD_TOKEN_FILE` names a file with a bot token, and is skipped otherwise.

Discord and its marks belong to Discord Inc.; see [BRANDING.md](BRANDING.md) for the icon's source.
