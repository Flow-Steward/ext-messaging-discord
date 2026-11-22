# Discord for Flow Steward

Send a text message to a Discord channel from a workflow. The extension also provides a read-only **Test connection** operation that returns the bot ID.

## Connect a bot

1. Create an application with a bot in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Install the bot in your server with the `bot` scope. Grant **View Channel** and **Send Messages** in the destination channel. To send in a thread, grant **Send Messages in Threads** as well.
3. In Flow Steward, create a **Discord bot** project connection and save its bot token in the **Bot token** secret field.
4. In the workflow builder, add **Send message**, select the connection and enter the channel ID and message. Discord's Developer Mode lets you copy the channel ID.

Messages are limited to 2,000 UTF-16 code units. Mention notifications are suppressed, and Flow Steward test-mode runs skip posting. Real sends require a logical workflow step execution ID. Discord deduplicates its derived nonce only within a short window. A timeout during a real send leaves the result uncertain because Discord may already have accepted it.

[Discord API reference](https://docs.discord.com/developers/reference) · [Create Message](https://docs.discord.com/developers/resources/message#create-message)
