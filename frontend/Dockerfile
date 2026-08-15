FROM node:20-slim

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

RUN npm run build

CMD ["npm", "start"]
