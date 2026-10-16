FROM node:20-alpine AS base
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
RUN corepack enable

FROM base AS deps
WORKDIR /app
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY frontend/package.json ./frontend/
COPY call/package.json ./call/
RUN --mount=type=cache,id=pnpm,target=/pnpm/store pnpm install --frozen-lockfile --filter call

FROM base AS builder
WORKDIR /app

# Build arguments for Next.js client-side variables
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_WS_URL
ARG NEXT_PUBLIC_ELEVENLABS_API_KEY
ARG NEXT_PUBLIC_ELEVENLABS_VOICE_ID

ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL
ENV NEXT_PUBLIC_ELEVENLABS_API_KEY=$NEXT_PUBLIC_ELEVENLABS_API_KEY
ENV NEXT_PUBLIC_ELEVENLABS_VOICE_ID=$NEXT_PUBLIC_ELEVENLABS_VOICE_ID
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY --from=deps /app/call/node_modules ./call/node_modules
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY call ./call

RUN pnpm --filter call build

FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3001
ENV HOSTNAME="0.0.0.0"

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

RUN mkdir -p /app/call/public

# Standalone output and static assets
COPY --from=builder --chown=nextjs:nodejs /app/call/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/call/.next/static ./call/.next/static

USER nextjs

EXPOSE 3001

# Next.js standalone runner automatically respects $PORT from Google Cloud Run
CMD ["node", "call/server.js"]
