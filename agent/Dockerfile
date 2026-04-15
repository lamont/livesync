FROM livesync-cli:local

# Deno — needed to run generate_setupuri.ts (same bootstrap as quartz-sync)
# Claude Code CLI — the agent's brain
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates unzip git \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://deno.land/install.sh | sh \
    && ln -s /root/.deno/bin/deno /usr/local/bin/deno \
    && npm install -g @anthropic-ai/claude-code

COPY generate_setupuri.ts /scripts/generate_setupuri.ts
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
