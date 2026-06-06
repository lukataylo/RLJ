# PulseGo driver PWA. Railway service root = driver-app/.
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_ORCHESTRATOR_URL
ARG VITE_MAPBOX_TOKEN
ENV VITE_ORCHESTRATOR_URL=$VITE_ORCHESTRATOR_URL
ENV VITE_MAPBOX_TOKEN=$VITE_MAPBOX_TOKEN
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /app/dist /usr/share/caddy
COPY Caddyfile /etc/caddy/Caddyfile
