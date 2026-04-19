FROM livesync-cli:local

# Deno + the upstream generate_setupuri.ts script so we can bootstrap
# settings.json with proper defaults (matches what Obsidian's setup URI flow
# produces). Plaintext-to-migrated settings end up with broken defaults
# (periodicReplication=false, batchSave=false, etc.) that prevent sync.
#
# jq — needed by multi-entrypoint.sh to parse CouchDB JSON responses.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates unzip jq \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://deno.land/install.sh | sh \
    && ln -s /root/.deno/bin/deno /usr/local/bin/deno

COPY generate_setupuri.ts /scripts/generate_setupuri.ts
COPY entrypoint.sh /entrypoint.sh
COPY multi-entrypoint.sh /multi-entrypoint.sh
RUN chmod +x /entrypoint.sh /multi-entrypoint.sh

# SYNC_MODE=single (default, backward compat) or multi (registry-driven)
ENV SYNC_MODE=single

# Override the livesync-cli entrypoint so we can run our own scripts
ENTRYPOINT []
CMD ["sh", "-c", "if [ \"$SYNC_MODE\" = \"multi\" ]; then exec /multi-entrypoint.sh; else exec /entrypoint.sh; fi"]
