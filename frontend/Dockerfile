FROM node:22-alpine

WORKDIR /app

# Install dependencies first for fast layer caching
COPY package*.json ./
RUN npm install

# Copy application source code
COPY . .

ENV NODE_ENV=development
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0"]
