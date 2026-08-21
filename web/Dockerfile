# Web image (Phase 5.7 seed for the Phase-9 compose; build context = web/).
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next ./.next
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/next.config.mjs ./next.config.mjs
# `next start` serves public/ from disk — without this the 05 Mind head is a 404
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["npm", "run", "start"]
