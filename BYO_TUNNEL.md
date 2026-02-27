# BYO Tunnel (Advanced)

Mnesis is local-first by default.

If you need to reach Mnesis from an online LLM client, you can expose your local backend with your own tunnel provider (ngrok, cloudflared, etc.).

This mode is advanced and unsupported by default.

## Security Baseline (Required)

1. Use a dedicated MCP key (do not reuse broad/shared tokens).
2. Keep snapshot query token disabled.
3. Keep snapshot token fallback for MCP disabled.
4. Keep MCP auth and rate-limiting enabled.
5. Rotate keys regularly.
6. Prefer short-lived tunnel sessions.
7. Proxied `/api/v1/*` calls require scoped Bearer auth (`read`/`write`/`admin`).
8. Allow your tunnel host in trusted hosts (`security.trusted_hosts`) or via
   `MNESIS_TRUSTED_HOSTS` env var (comma-separated).

## Example (ngrok)

```bash
ngrok http 7860
```

Then configure your online client MCP endpoint with:

`https://<your-ngrok-domain>/mcp/sse`

Use Bearer auth with your dedicated MCP key.

If your tunnel uses custom host headers, start backend with:

```bash
MNESIS_TRUSTED_HOSTS="127.0.0.1,localhost,testserver,*.ngrok-free.app,*.trycloudflare.com" npm run dev
```

## Recommended Scope

Use least privilege:

- `read` only if the client should never write.
- `read,write,sync` only when full memory operations are required.
