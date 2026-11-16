# The hosted conjur3-pilot MCP — the premium commands/code/knowledge.
# Pure Python + the MCP lib. NO FreeCAD, no Xvfb, no GPU: FreeCAD lives on the
# customer's machine and is reached over the relay tunnel. This image is tiny.
#
# BEFORE BUILDING: vendor the in-repo conjur3-pilot source next to this
# Dockerfile (the deploy scripts do this automatically):
#   rsync -a --exclude .venv conjur3/conjur3-pilot/ deploy/mcp/conjur3-pilot/
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY conjur3-pilot /opt/conjur3-pilot
RUN pip install --no-cache-dir /opt/conjur3-pilot

EXPOSE 8765
# Serve the MCP over HTTP; route its FreeCAD RPC at the relay (gateway:9000),
# which tunnels to the customer's connector → their local FreeCAD addon.
CMD ["conjur3-pilot", "--http", "--http-host", "0.0.0.0", "--http-port", "8765", \
     "--host", "gateway", "--port", "9000"]
