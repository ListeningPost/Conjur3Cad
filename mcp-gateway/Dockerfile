# Conjur3 MCP Gateway
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY tsconfig.json ./
COPY src ./src
RUN npm run build

# Tailscale static binaries — used only when TS_AUTHKEY is provided at runtime
# (userspace networking; lets the gateway reach the on-prem observability box
# over the tailnet with zero public exposure).
FROM tailscale/tailscale:stable AS tailscale

FROM node:20-slim AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY --from=build /app/dist ./dist
COPY --from=tailscale /usr/local/bin/tailscaled /usr/local/bin/tailscaled
COPY --from=tailscale /usr/local/bin/tailscale /usr/local/bin/tailscale
RUN mkdir -p /var/run/tailscale /var/lib/tailscale
# Connector installer + bundle (staged by `make connector-dist` / deploy scripts).
COPY public ./public
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh
EXPOSE 8080
CMD ["./entrypoint.sh"]
