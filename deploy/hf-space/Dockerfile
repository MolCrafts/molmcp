# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

ARG MOLMCP_REF=HEAD
ARG MOLPY_REF=HEAD

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

RUN for spec in "molmcp:${MOLMCP_REF}" "molpy:${MOLPY_REF}"; do \
        name="${spec%%:*}"; ref="${spec##*:}"; \
        git clone --depth 1 "https://github.com/MolCrafts/${name}.git" "${name}" && \
        if [ "${ref}" != "HEAD" ]; then \
            git -C "${name}" fetch --depth 1 origin "${ref}" && \
            git -C "${name}" checkout FETCH_HEAD; \
        fi; \
    done

RUN uv venv .venv
ENV VIRTUAL_ENV=$HOME/app/.venv \
    PATH=$HOME/app/.venv/bin:$PATH

# molexp comes in via the [tool.uv.sources] override declared in
# molmcp/packages/molmcp-molexp/pyproject.toml (Roy-Kid/molexp@dev).
RUN uv pip install \
        ./molpy \
        ./molmcp \
        ./molmcp/packages/molmcp-molpy \
        ./molmcp/packages/molmcp-molexp \
        ./molmcp/packages/molmcp-lammps \
        ./molmcp/apps/molmcp-gateway

EXPOSE 7860

CMD ["molmcp-gateway", \
     "--transport", "streamable-http", \
     "--host", "0.0.0.0", \
     "--port", "7860"]
