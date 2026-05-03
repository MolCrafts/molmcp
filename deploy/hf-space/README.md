---
title: molmcp Gateway
emoji: 🧪
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
license: bsd-3-clause
short_description: MolCrafts MCP gateway over streamable-http
---

# molmcp Gateway on Hugging Face Spaces

This Space runs the [molmcp](https://github.com/MolCrafts/molmcp) gateway server, exposing the molpy / molexp / lammps tool plugins to any MCP-compatible client over `streamable-http`.

## Endpoint

Once the Space is running, the MCP endpoint is reachable at:

```
https://<your-space-host>/mcp
```

Use this URL when configuring an MCP client (Claude Desktop, Continue, custom agent, etc.).

## Build args (optional)

The Dockerfile pulls three repos at build time. Pin them to specific commits/tags via Space settings → Variables and secrets → "Build args":

| Arg | Default | Purpose |
| --- | --- | --- |
| `MOLMCP_REF` | `master` | molmcp commit / branch / tag |
| `MOLPY_REF` | `master` | molpy commit / branch / tag |
| `MOLEXP_REF` | `master` | molexp commit / branch / tag |

## Auth note

A public free Space exposes the MCP endpoint to the internet without authentication. Anyone with the URL can invoke tools. Before sharing the URL widely, consider:

- Setting the Space to **private** (free tier supports this) so only your HF account can access it.
- Or front the gateway with a bearer-token middleware before exposing publicly.

## Cold start

Free Spaces sleep after ~48h of inactivity. The first request after sleep triggers a cold start that takes 30–60 s while the container boots and Python imports the scientific stack. Subsequent requests are warm and respond in milliseconds.
