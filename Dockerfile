FROM node:20-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
COPY apps/api/package.json apps/api/package.json
COPY apps/web/package.json apps/web/package.json
RUN npm install

FROM deps AS build
WORKDIR /app
COPY . .
RUN npm run build

FROM node:20-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production
COPY package.json package-lock.json* ./
COPY apps/api/package.json apps/api/package.json
RUN npm install --omit=dev --workspace apps/api
COPY --from=build /app/apps/api/dist apps/api/dist
COPY --from=build /app/apps/web/dist apps/web/dist
EXPOSE 3000
CMD ["node", "apps/api/dist/server.js"]
