# syntax=docker/dockerfile:1
#
# One fully static `aipod` binary (PyInstaller + staticx) in a `FROM scratch`
# image. The same image runs either mode:
#   docker run ... aipod:latest                 # server (default CMD)
#   docker run ... aipod:latest agent --host 0.0.0.0 --port 8080

# ---- build stage ----
FROM python:3.12-slim-bookworm AS build

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

RUN apt-get update \
 && apt-get install -y --no-install-recommends binutils patchelf ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY packaging ./packaging

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --group build

RUN uv run --no-sync pyinstaller packaging/aipod.spec --noconfirm \
        --distpath /out --workpath /tmp/pyi \
 && uv run --no-sync staticx --strip /out/aipod /out/aipod-static \
 && /out/aipod-static server --print contract --host build.local --port 0 > /dev/null

RUN mkdir -p /rootfs/tmp /rootfs/etc/ssl/certs \
 && chmod 1777 /rootfs/tmp \
 && printf 'app:x:1000:1000:app:/tmp:/sbin/nologin\n' > /rootfs/etc/passwd \
 && printf 'app:x:1000:\n' > /rootfs/etc/group \
 && cp /etc/ssl/certs/ca-certificates.crt /rootfs/etc/ssl/certs/ca-certificates.crt \
 && install -m 0755 /out/aipod-static /rootfs/aipod

# ---- runtime stage ----
FROM scratch

COPY --from=build /rootfs/ /

ENV TMPDIR=/tmp \
    HOME=/tmp \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    AIPOD_MCP_URL=http://aipod-server/mcp

USER 1000:1000
EXPOSE 8000 8080

ENTRYPOINT ["/aipod"]
CMD ["server", "--host", "0.0.0.0", "--port", "8000"]
