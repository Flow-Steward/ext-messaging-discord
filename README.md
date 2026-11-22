# Discord for Flow Steward

Send a text message to a Discord channel from a workflow. The extension also provides a read-only **Test connection** operation that returns the bot ID. Workflows can also read a channel, list a page of channel messages, read a server and list its channels.

## Connect a bot

1. Create an application with a bot in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Install the bot in your server with the `bot` scope. Grant **View Channel** and **Send Messages** in the destination channel. To send in a thread, grant **Send Messages in Threads** as well.
3. In Flow Steward, create a **Discord bot** project connection and save its bot token in the **Bot token** secret field.
4. In the workflow builder, add **Send message**, select the connection and enter the channel ID and message. Discord's Developer Mode lets you copy the channel ID.

Messages are limited to 2,000 UTF-16 code units. Mention notifications are suppressed, and Flow Steward test-mode runs skip posting. Real sends require a logical workflow step execution ID. Discord deduplicates its derived nonce only within a short window. A timeout during a real send leaves the result uncertain because Discord may already have accepted it.

[Discord API reference](https://docs.discord.com/developers/reference) · [Create Message](https://docs.discord.com/developers/resources/message#create-message)

## Discord REST v10 catalog

Use **Run Discord REST read** for a GET operation or **Run Discord REST write** for a mutation. Select an operation in the picker and use named path and query parameter objects. The runtime chooses the method, URI template and allowed success statuses from the pinned catalog.

- Select the **Discord bot**, **Discord OAuth2 token**, or **Discord webhook or interaction token** connection required by the endpoint. Choose the correct OAuth2 scopes in Discord. The OAuth2 token connection takes a manually issued bearer token and requires replacement on expiry. Interaction tokens are short-lived and scoped to an individual interaction. Store tokens in the project's secret fields. Body credentials for guild membership, group DMs, lobby joins and Partner SDK operations are injected from the Discord bot connection. Leave those fields out of the workflow body.
- For JSON or form bodies, put the provider body in a `data` field, for example `{"data":{"content":"Hello"}}`. The wrapper also supports array bodies. Choose another request media type when the endpoint requires it.
- Multipart files are a list of objects with `field`, `filename` and `data_base64`. Results that contain newly created webhook tokens omit those tokens. Retrieve and store webhook credentials through Discord's administration UI. Keep each request within the 2 MB extension upload budget. Responses are bounded at 256 KB. Use Discord pagination for larger lists.
- The reply exposes status, media type and response data. The runtime removes credential fields and reflected connection secrets from JSON output. PNG responses are base64-encoded.
- Test runs suppress writes. A failed network exchange on a write can leave Discord's result unknown. The runtime sends each request only once and reports available numeric rate-limit information. If Discord acknowledges a request and its response is too large or incomplete, the step returns its HTTP status and a warning without the response data.

Offline tests use mocked Discord responses. Live permissions, partner-only endpoints and provider-side payload validation require verification in an authorized Discord test environment. See [API coverage and review](docs/API-COVERAGE.md).
