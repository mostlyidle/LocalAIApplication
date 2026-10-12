# =============================================================================
# Frontend Dockerfile — Multi-stage build with pnpm + standalone output
# =============================================================================
# Produces a minimal production image using Next.js standalone output.
# Build:  docker build -t local-ai-frontend .
# Run:    docker run -p 3000:3000 local-ai-frontend
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Dependencies — install node_modules
# ---------------------------------------------------------------------------
FROM node:22-alpine AS deps

RUN corepack enable && corepack prepare pnpm@10.6.5 --activate

WORKDIR /app

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile --prod=false

# ---------------------------------------------------------------------------
# Stage 2: Build — compile Next.js application
# ---------------------------------------------------------------------------
FROM node:22-alpine AS builder

RUN corepack enable && corepack prepare pnpm@10.6.5 --activate

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Build-time environment variable for API URL
# In Docker, the browser still needs to reach the backend.
# Default assumes backend is exposed on the host at port 8000.
ENV NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_TELEMETRY_DISABLED=1

RUN pnpm build

# ---------------------------------------------------------------------------
# Stage 3: Runtime — minimal image with standalone output
# ---------------------------------------------------------------------------
FROM node:22-alpine AS runtime

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

# Copy standalone output
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=10s \
    CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:3000/ || exit 1

EXPOSE 3000

CMD ["node", "server.js"]
