# syntax=docker/dockerfile:1
# =============================================================================
# Tchiko Assistant: headless Tchiko RC server image
# =============================================================================
# Runs `main.py --remote`: the encrypted HTTPS/WSS Tchiko RC server plus the agent
# engine, without the GTK desktop companion. Pair from a browser on another device.
#
#   docker run -d --name tchiko -p 8765:8765 \
#     -e TCHIKO_RC_PUBLIC_URL=https://<docker-host-ip>:8765 \
#     -v tchiko-config:/app/config -v tchiko-experiences:/app/experiences \
#     -v tchiko-tls:/home/tchiko/.config/tchiko \
#     ghcr.io/zyniq-solutions/tchiko-assistant:2.0.0
#   docker logs -f tchiko        # one-step pairing link
# =============================================================================

ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm

ARG VERSION=dev
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown

LABEL org.opencontainers.image.title="Tchiko Assistant (headless RC)" \
      org.opencontainers.image.description="Autonomous Linux sysadmin & DevOps agent with the Tchiko RC end-to-end encrypted remote control server" \
      org.opencontainers.image.source="https://github.com/ZYNIQ-SOLUTIONS/Tchiko-Assistant-Sysadmin-companion" \
      org.opencontainers.image.url="https://github.com/ZYNIQ-SOLUTIONS/Tchiko-Assistant-Sysadmin-companion" \
      org.opencontainers.image.documentation="https://github.com/ZYNIQ-SOLUTIONS/Tchiko-Assistant-Sysadmin-companion#74-container-image-headless-tchiko-rc" \
      org.opencontainers.image.vendor="ZYNIQ SOLUTIONS" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/tchiko \
    USER=tchiko \
    SHELL=/bin/bash \
    TCHIKO_RC_PORT=8765 \
    TCHIKO_RC_TLS=1 \
    TCHIKO_PERMISSIONS=supervised

# bash is required (every agent tool runs via `/bin/bash -lc`); the rest makes the sysadmin
# toolkit useful inside the container. tini is PID 1: signal forwarding + zombie reaping.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      bash ca-certificates curl dnsutils git iproute2 iputils-ping lsof \
      openssh-client openssl procps tini \
 && rm -rf /var/lib/apt/lists/*

# Native ECDH/AES-GCM and TLS certificate generation (pure-Python fallbacks exist, but are slower
# and not constant-time). Prebuilt wheels exist for amd64 and arm64.
RUN pip install "cryptography>=44,<50"

RUN groupadd --gid 10001 tchiko \
 && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/tchiko --shell /bin/bash tchiko

WORKDIR /app

# Code and static assets: root-owned, read-only for the runtime user.
COPY main.py pyproject.toml LICENSE ./
COPY tchiko/ tchiko/
COPY rc/ rc/
COPY skills/ skills/
COPY --chmod=0755 docker/entrypoint.sh /usr/local/bin/tchiko-entrypoint
COPY --chmod=0755 docker/healthcheck.py /usr/local/bin/tchiko-healthcheck

# Runtime state: writable by the runtime user, persisted via volumes.
COPY --chown=tchiko:tchiko antigravity.yaml ./
COPY --chown=tchiko:tchiko experiences/ experiences/
RUN python -m compileall -q main.py tchiko \
 && mkdir -p /app/config /home/tchiko/.config/tchiko \
 && chown tchiko:tchiko /app/config /home/tchiko/.config /home/tchiko/.config/tchiko \
 && chmod 0700 /home/tchiko/.config/tchiko

USER tchiko

VOLUME ["/app/config", "/app/experiences", "/home/tchiko/.config/tchiko"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python", "/usr/local/bin/tchiko-healthcheck"]

STOPSIGNAL SIGTERM
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/tchiko-entrypoint"]
CMD []
