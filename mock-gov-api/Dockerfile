FROM node:22.18.0-alpine3.22

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=8080

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force

COPY src ./src

USER node
EXPOSE 8080

CMD ["node", "src/server.js"]
