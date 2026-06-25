FROM python:3.11-slim

# System deps for Playwright Chromium + Chinese fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk-bridge2.0-0 libdrm2 libxkbcommon0 \
    libgbm1 libasound2 libxcomposite1 libxdamage1 \
    libxrandr2 libpango-1.0-0 libcairo2 libcups2 \
    libdbus-1-3 libexpat1 libxfixes3 \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for Playwright
RUN useradd -m -s /bin/bash pptruser

WORKDIR /app

# Copy source and config (leverages Docker layer cache)
COPY pyproject.toml ./
COPY src/ ./src/
COPY domains/ ./domains/

# Install project with stealth extra + Playwright browser
RUN pip install --no-cache-dir ".[stealth]" && \
    playwright install chromium

# Switch to non-root user
USER pptruser

EXPOSE 8000

# Default: start MCP server in streamable-http mode
CMD ["agentic-playwright-mcp", "serve", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
