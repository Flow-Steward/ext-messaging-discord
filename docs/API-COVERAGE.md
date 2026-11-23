# Discord API coverage and review

The upstream [Discord REST v10 inventory](https://github.com/discord/discord-api-spec/blob/3a21a01249a763cd47f1dfec3da91c5ba71bb974/specs/openapi.json) is pinned at `3a21a01249a763cd47f1dfec3da91c5ba71bb974`. The vendored file is `tests/reference/discord-openapi.json` with SHA-256 `ef338088f4c6a73fdb9840acd1ce2bf8f16c1870f4437bfc563418c7e0de7278`. Its upstream license is beside the fixture. The public description is a preview and can disagree with the endpoint documentation. Use the endpoint documentation to resolve discrepancies.

The [REST inventory](discord-rest-inventory.json) enumerates 250 operations across 157 paths. For each operation it records its method, path template, declared authorization alternatives, request media types and success statuses.

The dedicated action registry combines the 250 pinned OpenAPI operations with eight entries from the [Discord API documentation snapshot](https://github.com/discord/discord-api-docs/tree/9b737ec51ee8d5076af0565d209a9adf8f590a27). The [documentation fixture](../tests/reference/discord-docs-routes.json) records each source page, extracted request and authorization facts, and a SHA-256 digest of the canonical JSON facts. The test suite reconciles both inputs against the route, contract, action and form registries.

## Execution coverage

Each of the 258 entries has a separate `rest_<operation_id>` action, typed contract and workflow form. Discord accepts requests on 257 of those routes. The batch permissions route has an action that reports `operation_disabled` without sending a request because Discord disabled the endpoint in Permissions v2. Archived generic read and write pickers retain their original options for existing workflows.

| Documentation page | Additional dedicated actions |
| --- | --- |
| [SKUs](https://github.com/discord/discord-api-docs/blob/9b737ec51ee8d5076af0565d209a9adf8f590a27/developers/resources/sku.mdx) | `rest_list_application_skus` |
| [Application Identity Profiles](https://github.com/discord/discord-api-docs/blob/9b737ec51ee8d5076af0565d209a9adf8f590a27/developers/resources/application-identity-profile.mdx) | `rest_get_application_identity_profile`, `rest_update_application_identity_profile`, `rest_list_application_identities_by_external_id`, `rest_list_application_identities_by_user_id`, `rest_delete_application_identity` |
| [Guilds](https://github.com/discord/discord-api-docs/blob/9b737ec51ee8d5076af0565d209a9adf8f590a27/developers/resources/guild.mdx) | `rest_modify_current_user_nick` (deprecated by Discord) |
| [Application Commands](https://github.com/discord/discord-api-docs/blob/9b737ec51ee8d5076af0565d209a9adf8f590a27/developers/interactions/application-commands.mdx) | `rest_batch_edit_application_command_permissions` (disabled by Discord) |

The generated contracts expose named path and query fields and use the bounded JSON Schema subset that Flow Steward can execute. Discord performs final payload and permission validation.

The table lists the dedicated workflow actions that provide a narrower interface to frequently used endpoints.

## Dedicated actions

| Discord operation | Flow Steward operation | Evidence |
| --- | --- | --- |
| `get_my_user` | `test_connection` | Mocked bot identity response; live check with `DISCORD_TOKEN_FILE` |
| `create_message` | `send_message` | Mocked text send, test run without effect, uncertain outcome. The dedicated step sends text; use `rest_create_message` for embeds, components and files. |
| `get_channel` | `get_channel` | Mocked channel response and unreadable answers |
| `list_messages` | `list_messages` | Mocked page, cursor, limit and `all_pages` |
| `get_guild` | `get_guild` | Mocked server and count flag |
| `list_guild_channels` | `list_guild_channels` | Mocked empty channel list |

## Lists read page after page

Every GET operation whose query takes `limit` with `before` and/or `after` has the `all_pages` input (a test reconciles the list with the specification). The step reads page after page with the exact cursor: going `before` continues from the smallest cursor read, going `after` from the largest. Without a cursor, `after` lists start at `after=0` and `before` lists start at the newest item. A list is `complete` only after an empty page, or `has_more: false` where Discord reports it. A list stops early, with `complete: false`, `next_cursor` and a warning, before a page that would not fit the step output, after 15 seconds, or when Discord rate limits or drops a later page. Only whole pages are returned.

| Operation | Items | Cursor | Directions |
| --- | --- | --- | --- |
| `get_entitlements` | answer | `id` | after, before |
| `list_messages` | answer | `id` | before, after (`around` reads one page) |
| `list_pins` | `items` | `pinned_at` | before |
| `list_message_reactions_by_emoji` | answer | `id` | after |
| `get_answer_voters` | `users` | `id` | after |
| `list_thread_members` | answer | `user_id` | after |
| `list_private_archived_threads`, `list_public_archived_threads` | `threads` | `thread_metadata.archive_timestamp` | before |
| `list_my_private_archived_threads` | `threads` | `id` | before |
| `list_guild_audit_log_entries` | `audit_log_entries` | `id` | before, after |
| `list_guild_bans` | answer | `user.id` | after, before |
| `list_guild_members` | answer | `user.id` | after |
| `get_guild_join_requests` | `guild_join_requests` | `id` | after, before |
| `list_guild_scheduled_event_users`, `list_guild_scheduled_event_exception_users` | answer | `user_id` | after, before |
| `get_sku_subscriptions` | answer | `id` | after, before |
| `list_my_guilds` | answer | `id` | after, before |

`thread_search` and `guild_search` page by `offset` and are read one page at a time.

## Answers

A Discord answer is read up to 8 MiB. The whole step result, envelope included, stays within 3,500,000 serialized bytes, 2,000,000 values and keys and 48 levels of nesting.

A read fails without an external effect when its answer cannot be returned: `response_too_large` for an answer over 8 MiB or a result over the budget; `invalid_response` for a 2xx status the operation does not document, an answer cut off by the connection, an empty body where Discord documents one, an undocumented Content-Type, a body that does not parse, or one nested more than 45 levels.

A write follows table T, the first rule that applies decides: an undocumented 2xx status → `timeout_unknown`; JSON documented and another Content-Type → `timeout_unknown`; a body not read in full → success with `data: null` and a warning; an empty body → success; JSON documented and the body is not JSON → `timeout_unknown`; a body nested too deeply or too large for the output → success with `data: null` and a warning; otherwise success. Every confirmed write returns `processing: completed`. A test run returns `external_effect_status: failed` with `definitely_no_external_effect: true` and `processing: null`.

## Files

Multipart steps take workflow files in `file_artifacts` (`field`, `filename`, `artifact_handle`; granted through `contracts/artifact_policies.yaml` and read with `read_artifact_bytes`) and small files as base64 in `files`. The Content-Type of a part follows the extension of the file name from the types in Discord's [reference](https://github.com/discord/discord-api-docs/blob/9b737ec51ee8d5076af0565d209a9adf8f590a27/developers/reference.mdx) (image formats and the image, video and audio file groups); other files are `application/octet-stream`. A sticker must be a PNG, APNG, GIF or Lottie JSON file of at most 512 KiB. Each file is at most 20 MiB, Discord's default upload limit per file in the same reference; it names no limit per request, so a request carries at most ten files. Base64 files in `files` share the step input limit; larger files go in `file_artifacts`.

## Rate limits

Every step returns `rate_limit` (`limit`, `remaining`, `reset_after`, `bucket`, `global`) from Discord's `X-RateLimit-*` headers. An HTTP 429 answer fails with `rate_limited`, `retry_after_seconds` and `rate_limit_global`. No request is repeated automatically.

## Verification scope

Offline tests cover the fixed route for each executable action, all multipart routes, unreadable answers, table T, lists, files, response credential redaction, test runs and rate limit facts. `tests/test_live.py` reads the bot identity and its servers from the real API (GET only) when `DISCORD_TOKEN_FILE` is set. Live permission and payload verification of the other operations requires a dedicated test guild, Discord application and scoped authorization. Gateway, Voice and inbound interaction delivery have their own non-REST transports.

Webhook and interaction tokens in a route are taken from the **Discord webhook or interaction token** connection. Interaction responses go through such a connection holding the interaction token, which Discord keeps valid for 15 minutes.

## Mutation replay

Flow Steward claims mutating steps in its external-effect ledger before invoking the subprocess. The extension makes one upstream attempt. A lost response leaves the effect unresolved. Discord message creation also carries a deterministic nonce for the provider's short deduplication window. Discord does not expose a general idempotency key for all mutations.

Token-returning Partner SDK operations return status and non-credential fields. Returned tokens and credential-bearing webhook URLs are scrubbed before the result is available to a workflow. A value found in an answer under a credential field name is removed from other text only when it is at least eight characters long; the connection's own secrets are always removed.
