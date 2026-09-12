# Python 3.12, Node 22 and FFmpeg in one image, so a checkout with nothing
# installed on the host can run the whole app. See devcontainer.json.
#
# Both base images are pinned by digest. A tag moves under you - the failure
# Phase A removed from the backend's dependencies - and a devcontainer that
# floats is a second, quieter copy of it. Dependabot's docker entry for
# /.devcontainer bumps these digests by PR.

# Node is copied out of the official image rather than added through a
# devcontainer "feature": features are pinned by major tag and float. Both
# stages are Debian bookworm, so the copied binary's glibc is the one it was
# built against.
FROM node:26-bookworm-slim@sha256:cd9f682fa2885cd1056e830424764158570061c59736a1da836bc3d73df095ae AS node

FROM mcr.microsoft.com/devcontainers/python:3.14-bookworm@sha256:8179b9d5f68dab0def4e113f924e6aed989a636e65ab58fbe0c8e808b046ac40

# The base image ships a Yarn apt source whose signing key has since rotated,
# which fails `apt-get update` outright. Nothing here uses Yarn - the frontend
# is npm - so the source is removed rather than re-keyed.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
