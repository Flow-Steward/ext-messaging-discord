# Changelog

## 0.1.0

- Connect a Discord bot to a Flow Steward project.
- Verify the connection and send text messages to a channel from workflows.
- Add registry-backed REST read and write steps for 250 Discord v10 operation IDs.
- Support scoped bot, OAuth2 bearer, webhook and interaction credentials.
- Support JSON, URL-encoded and bounded multipart requests, with bounded JSON, CSV and PNG responses.
- Suppress writes in test mode and add operation-by-operation offline routing tests.
- Add 250 individually selectable Discord REST v10 actions with generated input contracts, forms and mutation effects.
- Validate dedicated action inputs and test each action against its pinned method and path.
- Fail a read with `invalid_response` or `response_too_large` when Discord's answer cannot be returned, instead of an empty result.
- Decide every write outcome with one table: an undocumented 2xx status or a non-JSON answer where JSON is documented is an unknown outcome; a confirmed write whose answer cannot be read succeeds without data and with a warning.
- Read Discord answers up to 8 MiB and keep each step's whole result within 3,500,000 bytes, 2,000,000 values and 48 levels.
- Add `all_pages` to the 17 Discord list operations with cursors: exact continuation, `next_cursor`, `complete` and `pages`.
- Accept workflow files (`file_artifacts`) next to base64 files; set each part's Content-Type from the file extension; check sticker files.
- Return `rate_limit` from Discord's headers on every step, and `retry_after_seconds` and `rate_limit_global` on HTTP 429.
- Report test runs of writes as no effect, and report a disabled Discord operation before the test-run check.
- Send every request through the SDK's pinned opener.
- Require at least eight characters in every secret field of a connection, and remove a value from other text only when it is at least eight characters long, whether it comes from the connection or from the answer.
- Treat an answer cut off before its end (fewer bytes than Content-Length, or a chunked answer that stops early) as not read: a read fails with `invalid_response`, a confirmed write succeeds without data and with a warning.
- Name what is outside this version: receiving interactions and answering them within 3 seconds with the event's token, the Gateway and Voice.
- Name the repository and issue tracker in the manifest; add CI, release, CodeQL and catalog checks.
- Add a read-only live test that runs when `DISCORD_TOKEN_FILE` is set.
- Send workflow files without holding them in memory: each is streamed to a temporary file and checked, then the multipart body goes piece by piece with its Content-Length.
- Name every limit as a constant with its source; size messages are formed from the constant they check.
