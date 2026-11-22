# Discord API coverage and review

The upstream [Discord REST v10 inventory](https://github.com/discord/discord-api-spec/blob/3a21a01249a763cd47f1dfec3da91c5ba71bb974/specs/openapi.json) is pinned at `3a21a01249a763cd47f1dfec3da91c5ba71bb974`. The vendored file is `tests/reference/discord-openapi.json` with SHA-256 `ef338088f4c6a73fdb9840acd1ce2bf8f16c1870f4437bfc563418c7e0de7278`. Its upstream license is beside the fixture. The public description is a preview and can disagree with the endpoint documentation. Use the endpoint documentation to resolve discrepancies.

The [REST inventory](discord-rest-inventory.json) enumerates 250 operations across 157 paths. For each operation it records its method, path template, declared authorization alternatives, request media types and success statuses.

The runtime route registry is generated with `python scripts/build_rest_registry.py`. The route tests verify method, path binding and statuses for all 250 entries and verify the generated data against the pinned specification. These checks cover route construction. The action coverage table tracks what Flow Steward users can invoke.

## Execution coverage

Every operation in the pinned registry can be selected by ID through the REST read or write workflow action. The dispatcher tests exercise all 250 registered routes with mocked transport, including connection selection, fixed path binding and response statuses. Separate tests exercise write suppression. The spec is the route contract. Discord validates provider-specific body fields and permissions.

The table lists the dedicated workflow actions that provide a narrower interface to frequently used endpoints.

## Dedicated actions

| Discord operation | Flow Steward operation | Evidence |
| --- | --- | --- |
| `get_my_user` | `test_connection` | Mocked bot identity response |
| `create_message` | `send_message` | Mocked text send, suppressed test send and uncertain response. Multipart uploads remain pending. |

| `get_channel` | `get_channel` | Mocked channel response |
| `list_messages` | `list_messages` | Mocked page, cursor and limit |
| `get_guild` | `get_guild` | Mocked server and count flag |
| `list_guild_channels` | `list_guild_channels` | Mocked empty channel list |

## Release review

- Reconcile every inventory row against the Discord endpoint documentation. Record authorization, required permissions, request shape, success statuses and whether the operation can change Discord state.
- Add a closed operation contract and tests for each supported row. Keep bot tokens, OAuth2 tokens and webhook or interaction tokens in the corresponding connection or ephemeral execution scope. Discord returns secrets on some routes. Review those responses before exposing outputs to workflows.
- Cover JSON, form encoding, multipart attachments and no-content responses. Prove that dry runs suppress mutations and that timeouts do not blindly retry writes.
- Track [OAuth2](https://docs.discord.com/developers/topics/oauth2), [Gateway](https://docs.discord.com/developers/events/gateway), [Interactions](https://docs.discord.com/developers/interactions/receiving-and-responding) and [Voice](https://docs.discord.com/developers/topics/voice-connections) alongside REST. Gateway and Voice need a persistent service with its own lifecycle. Inbound Interactions need Ed25519 signature verification and a public callback.
- Run offline checks for all operation contracts. Run live integration checks in a dedicated test guild and Discord application, with fixtures for permissions and scoped authorization.
- Review runtime and release artifacts, build and verify the bundle, push the source, then record review and release evidence.
