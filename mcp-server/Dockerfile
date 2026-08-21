FROM node:22.18.0-alpine3.22

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000 \
    GOV_API_BASE_URL=http://mock-gov-api:8080

WORKDIR /app

COPY package.json package-lock.json ./
COPY vendor ./vendor
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force

COPY src ./src

USER node
EXPOSE 3000

CMD ["node", "src/server.js"]
