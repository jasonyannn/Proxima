"""Launch the Proxima MCP server.

Two transports, because MCP clients are split between them:

``stdio``  — the client starts this process and talks over a pipe. VS Code,
             Claude Code, Claude Desktop and Codex all do this. Nothing listens
             on a port, so there is nothing to secure.

``http``   — streamable HTTP on a URL, for clients that take an endpoint rather
             than a command, and for running Proxima somewhere other than the
             machine the client is on.

The HTTP transport binds to localhost and refuses to serve a non-local
interface without a token. That is not paranoia: this server reads and writes a
product backlog, and a streamable-HTTP endpoint on 0.0.0.0 with no auth is an
open door to it.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from .context import ResolutionError, context_from_env
from .server import build_server


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="proxima-mcp",
        description="Expose Proxima's backlog, competitor and IP analysis over MCP.",
    )
    parser.add_argument(
        "--transport", choices=["stdio", "http"], default="stdio",
        help="stdio (default) for editor-launched clients; http for a URL endpoint.",
    )
    parser.add_argument(
        "--owner", default=None,
        help="Account id or email whose workspaces to expose. Defaults to the "
             "only local account, or $PROXIMA_OWNER.",
    )
    parser.add_argument(
        "--workspace", default=None,
        help="Workspace id used when a tool call names none. Defaults to the "
             "most recent chat, or $PROXIMA_WORKSPACE.",
    )
    parser.add_argument(
        "--read-only", action="store_true",
        help="Register only the read tools. Nothing can write to a workspace.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address.")
    parser.add_argument("--port", type=int, default=8765, help="HTTP port.")
    parser.add_argument("--path", default="/mcp", help="HTTP endpoint path.")
    parser.add_argument(
        "--stateless", action="store_true",
        help="Serve each request independently, with no session. Required by "
             "serverless hosts that do not keep a process between requests.",
    )
    parser.add_argument(
        "--allow-host", action="append", default=[], metavar="HOST",
        help="Extra Host header to accept (repeatable). Needed when reaching "
             "the server through a proxy or tunnel.",
    )
    parser.add_argument(
        "--name", default="proxima", help="Server name reported to the client."
    )
    return parser


class _BearerToken:
    """Reject HTTP requests without the shared token.

    A plain ASGI wrapper rather than Starlette middleware so that lifespan
    messages — which start and stop the session manager — pass through
    untouched. The token is compared in constant time; a timing signal on a
    local dev server is not a real threat, but writing the leaky version is how
    the leaky version ends up somewhere it matters.
    """

    def __init__(self, app: Any, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        import hmac

        header = ""
        for key, value in scope.get("headers") or []:
            if key.lower() == b"authorization":
                header = value.decode("latin-1")
                break

        offered = header[7:] if header.lower().startswith("bearer ") else ""
        if not hmac.compare_digest(offered, self.token):
            body = b'{"error":"unauthorized"}'
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer"),
                    (b"content-length", str(len(body)).encode()),
                ],
            })
            await send({"type": "http.response.body", "body": body})
            return

        await self.app(scope, receive, send)


def _serve_http(server: Any, args: argparse.Namespace) -> int:
    import uvicorn
    from mcp.server.transport_security import TransportSecuritySettings

    token = os.environ.get("PROXIMA_MCP_TOKEN", "").strip()
    local = args.host in {"127.0.0.1", "localhost", "::1"}
    if not local and not token:
        print(
            f"error: refusing to serve {args.host} without authentication.\n"
            "       Set PROXIMA_MCP_TOKEN to a shared secret, or bind 127.0.0.1\n"
            "       and reach it through a tunnel.",
            file=sys.stderr,
        )
        return 2

    # DNS-rebinding protection is on by default and checks the Host header, so
    # anything fronting this server has to be named explicitly.
    allowed = {args.host, f"{args.host}:{args.port}", "127.0.0.1",
               f"127.0.0.1:{args.port}", "localhost", f"localhost:{args.port}"}
    allowed.update(args.allow_host)

    app = server.streamable_http_app(
        streamable_http_path=args.path,
        stateless_http=args.stateless,
        host=args.host,
        transport_security=TransportSecuritySettings(
            allowed_hosts=sorted(allowed),
            allowed_origins=["*"],
        ),
    )
    if token:
        app = _BearerToken(app, token)

    url = f"http://{args.host}:{args.port}{args.path}"
    print(f"→ Proxima MCP on {url}"
          f"{'  (bearer token required)' if token else ''}"
          f"{'  [read-only]' if args.read_only else ''}", file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    try:
        context = context_from_env(args.owner, args.workspace, args.read_only)
    except ResolutionError as exc:
        # stderr, always: on stdio this process's stdout is the protocol
        # channel, and one stray line on it breaks the client's parser.
        print(f"error: {exc}", file=sys.stderr)
        return 2

    server = build_server(context, name=args.name)

    if args.transport == "stdio":
        server.run("stdio")
        return 0
    return _serve_http(server, args)


if __name__ == "__main__":
    raise SystemExit(main())
