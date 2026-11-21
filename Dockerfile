# syntax=docker/dockerfile:1

# Both stages must use the same Python base so the venv's interpreter symlinks
# resolve in the final image. Pin by digest in CI for reproducible builds, e.g.
#   python:3.15-slim-trixie@sha256:<digest>
ARG PYTHON_IMAGE=python:3.15-slim-trixie

# ---------------------------------------------------------------------------
# Build stage: resolve and install locked dependencies into /app/.venv
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_NO_DEV=1

WORKDIR /app

# Install third-party dependencies first so this layer is cached independently
# of application source changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-editable

# Install the project itself as a regular (non-editable) package so the final
# image needs only the venv, not the source tree.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-editable

# ---------------------------------------------------------------------------
# Runtime stage: minimal image with only the interpreter and the venv
# ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

# Drop pip from the runtime image; nothing should be installed at runtime.
RUN python -m pip uninstall --yes pip \
 && groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app \
      --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin app

# Owned by root and not writable by the runtime user.
COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1

WORKDIR /app

# Numeric UID so Kubernetes `runAsNonRoot` can verify it without /etc/passwd.
USER 10001:10001

ENTRYPOINT ["gcp-janitor"]
CMD ["--help"]
