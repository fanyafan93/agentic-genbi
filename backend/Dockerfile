FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install codex CLI so CodexSdkAnalysisRuntime can launch Codex subprocesses inside the container.
# We fetch the official Node.js 20.x linux-x64 tarball directly so we do not depend on any
# third-party apt repository. Then install the @openai/codex npm package globally.
ARG NODE_VERSION=20.18.0
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.gz" -o /tmp/node.tar.gz \
    && mkdir -p /usr/local/lib/nodejs \
    && tar -xzf /tmp/node.tar.gz -C /usr/local/lib/nodejs --strip-components=1 \
    && ln -s /usr/local/lib/nodejs/bin/node /usr/local/bin/node \
    && ln -s /usr/local/lib/nodejs/bin/npm /usr/local/bin/npm \
    && ln -s /usr/local/lib/nodejs/bin/npx /usr/local/bin/npx \
    && npm install -g @openai/codex@latest \
    && npm install -g @benborla29/mcp-server-mysql@latest \
    && ln -s /usr/local/lib/nodejs/bin/codex /usr/local/bin/codex \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /tmp/node.tar.gz

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "backend.api.analysis_api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
