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
| `get_my_user` | `test_connection` | Mocked bot identity response |
| `create_message` | `send_message` | Mocked text send, suppressed test send and uncertain response. The dedicated step sends text. Use the REST write step for multipart. |
| `get_channel` | `get_channel` | Mocked channel response |
| `list_messages` | `list_messages` | Mocked page, cursor and limit |
| `get_guild` | `get_guild` | Mocked server and count flag |
| `list_guild_channels` | `list_guild_channels` | Mocked empty channel list |

## Verification scope

Offline tests cover the fixed route for each executable action, all multipart routes, response credential redaction, and write suppression and ambiguous outcomes. Live permission and payload verification requires a dedicated test guild, Discord application and scoped authorization. Gateway, Voice, and inbound interaction delivery have their own non-REST transports.

## Mutation replay

Flow Steward claims mutating steps in its external-effect ledger before invoking the subprocess. The extension makes one upstream attempt. A lost response leaves the effect unresolved. Discord message creation also carries a deterministic nonce for the provider’s short deduplication window. Discord does not expose a general idempotency key for all mutations.

Token-returning Partner SDK operations return status and non-credential fields. Returned tokens and credential-bearing webhook URLs are scrubbed before the result is available to a workflow.
