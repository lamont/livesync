FROM livesync-cli:local

# Deno + the upstream generate_setupuri.ts script so we can bootstrap
# settings.json with proper defaults (matches what Obsidian's setup URI flow
# produces). Plaintext-to-migrated settings end up with broken defaults
# (periodicReplication=false, batchSave=false, etc.) that prevent sync.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates unzip \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://deno.land/install.sh | sh \
    && ln -s /root/.deno/bin/deno /usr/local/bin/deno

COPY generate_setupuri.ts /scripts/generate_setupuri.ts
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
