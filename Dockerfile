FROM python:3.11-slim

WORKDIR /app

# Install the package
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

RUN pip install --no-cache-dir -e ".[langgraph,otel]"

# Dashboard port
EXPOSE 8765

# Default: serve the dashboard (users override CMD to run their own script)
CMD ["pixelpulse", "serve"]
