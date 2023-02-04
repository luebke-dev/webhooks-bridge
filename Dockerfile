FROM python:3.11-alpine
RUN pip install poetry && \
    poetry config virtualenvs.create false
COPY ./pyproject.toml ./app/poetry.lock* /code/
WORKDIR /code
RUN poetry install --no-root --no-dev
COPY webhooks_bridge/* /code/webhooks_bridge/
CMD ["uvicorn", "webhooks_bridge.main:app", "--proxy-headers", "--forwarded-allow-ips", "'*'", "--host", "0.0.0.0", "--port", "80"]
