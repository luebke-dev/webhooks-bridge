FROM python:3.11-alpine

# Install build dependencies for some Python packages
RUN apk add --no-cache gcc musl-dev libffi-dev

# Install poetry
RUN pip install poetry && \
    poetry config virtualenvs.create false

# Copy dependency files
COPY ./pyproject.toml ./poetry.lock* /code/
WORKDIR /code

# Install dependencies
RUN poetry install --no-root --only main

# Copy application code
COPY webhooks_bridge/* /code/webhooks_bridge/

# Create config directory
RUN mkdir -p /config

# Set proper permissions and create non-root user
RUN adduser -D -s /bin/sh appuser && \
    chown -R appuser:appuser /code /config
USER appuser

# Run the application
CMD ["uvicorn", "webhooks_bridge.main:app", "--proxy-headers", "--forwarded-allow-ips", "*", "--host", "0.0.0.0", "--port", "80"]
