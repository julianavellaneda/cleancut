FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# Nothing about the backend's location is baked in. The browser calls a
# relative /api and the Next server proxies it to BACKEND_ORIGIN, which is read
# at start time - so this image is not pinned to whichever origin built it.
RUN npm run build

CMD ["npm", "start"]
