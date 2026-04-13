FROM node:22-alpine

RUN apk add --no-cache git coreutils

WORKDIR /app

# Pin to a known-good Quartz v4 commit for reproducibility.
RUN git clone --depth 1 https://github.com/jackyzha0/quartz.git . \
    && npm ci

EXPOSE 8080

# --directory points at the vault mount; --serve watches for changes.
CMD ["npx", "quartz", "build", "--serve", "--port", "8080", "--directory", "/vault"]
