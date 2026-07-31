# The private n8n image: stock n8n plus the PWR signature nodes (Task 4).
#
# The extension path is /opt/n8n-custom and NOT /home/node/.n8n/custom, because
# the persistent `n8n_data` volume is mounted over /home/node/.n8n and would
# mask anything the image put there -- the nodes would silently disappear on
# every deployment that already has a volume.
FROM node:22-alpine AS builder
WORKDIR /build/n8n-nodes-pwr
COPY custom-nodes/n8n-nodes-pwr/package.json ./
COPY custom-nodes/n8n-nodes-pwr/package-lock.json ./
RUN npm ci
COPY custom-nodes/n8n-nodes-pwr/tsconfig.json ./
COPY custom-nodes/n8n-nodes-pwr/src ./src
RUN npm run build && npm prune --omit=dev

FROM docker.n8n.io/n8nio/n8n:2.13.3@sha256:44a8df8aa3de533db83e07ef395f461471d217a965e78e1fc822e641a4904118
USER root
RUN mkdir -p /opt/n8n-custom/n8n-nodes-pwr
COPY --from=builder --chown=node:node \
  /build/n8n-nodes-pwr/package.json \
  /opt/n8n-custom/n8n-nodes-pwr/package.json
COPY --from=builder --chown=node:node \
  /build/n8n-nodes-pwr/dist \
  /opt/n8n-custom/n8n-nodes-pwr/dist
COPY --from=builder --chown=node:node \
  /build/n8n-nodes-pwr/node_modules \
  /opt/n8n-custom/n8n-nodes-pwr/node_modules
ENV N8N_CUSTOM_EXTENSIONS=/opt/n8n-custom
USER node
