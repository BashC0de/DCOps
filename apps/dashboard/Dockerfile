FROM node:20-bookworm-slim AS base
ENV NODE_ENV=development
WORKDIR /app

# Install only manifests first for layer caching.
COPY package.json ./

# `npm install` (not `npm ci`) since there's no lockfile committed yet.
RUN npm install --no-audit --no-fund

# Source is volume-mounted in dev. In a prod build you'd `COPY . .` and `npm run build`.

EXPOSE 3000
CMD ["npm", "run", "dev"]
