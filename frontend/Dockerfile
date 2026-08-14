# Frontend container.
#
# This runs the Vite dev server rather than a production bundle, on purpose:
# the dev server carries the /api and /health proxy that points at the API
# container, so the browser only ever talks to one origin and there is no CORS
# or runtime-config step to get wrong during a demo. For a public deployment,
# build with `vite build` and serve the nitro output behind a reverse proxy.

FROM node:22-slim

WORKDIR /app

# Install dependencies first so edits to source don't re-run the install.
COPY package.json ./
COPY bun.lock* package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY . .

EXPOSE 8080

# --host makes the server reachable from outside the container.
CMD ["npx", "vite", "dev", "--host", "0.0.0.0", "--port", "8080"]
