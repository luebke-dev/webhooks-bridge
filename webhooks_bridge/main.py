import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiofiles
import httpx
from fastapi import FastAPI, HTTPException, Request
from jinja2 import BaseLoader, Environment
from pydantic_settings import BaseSettings
from yaml import safe_load


class Settings(BaseSettings):
    config_path: str = "/config/"
    log_level: str = "ERROR"

    model_config = {"env_prefix": "WEBHOOKS_BRIDGE_"}


settings = Settings()

# Global HTTP client with proper SSL verification
http_client: httpx.AsyncClient | None = None


def ensure_config_directory() -> Path:
    """Ensure config directory exists and return its path."""
    config_dir = Path(settings.config_path)
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # In test environments or when /config is not writable, use a temp directory
        import tempfile

        config_dir = Path(tempfile.mkdtemp())
        settings.config_path = str(config_dir)
    return config_dir


def setup_logging() -> None:
    """Setup logging configuration."""
    config_dir = ensure_config_directory()
    log_file = config_dir / "webhooks.log"
    logging.basicConfig(
        filename=str(log_file),
        encoding="utf-8",
        level=getattr(logging, settings.log_level.upper(), logging.ERROR),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


# Setup logging when module is imported
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifespan events."""
    global http_client
    # Startup
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        verify=True,  # Enable SSL verification for security
        follow_redirects=True,
    )
    yield
    # Shutdown
    if http_client:
        await http_client.aclose()


app = FastAPI(title="Webhooks Bridge", version="0.2.0", lifespan=lifespan)


def render_string(string: str, values: dict[str, Any]) -> str:
    """Render a Jinja2 template string with the provided values."""
    try:
        template = Environment(loader=BaseLoader()).from_string(string)
        rendered = template.render(**values)
        return rendered
    except Exception as e:
        logging.error(f"Failed to render template string: {string}. Error: {e}")
        raise ValueError(f"Template rendering failed: {e}") from e


def evaluate_condition(string: str, values: dict[str, Any]) -> bool:
    """Evaluate a condition string using template rendering and YAML parsing."""
    try:
        rendered = render_string(string, values)
        loaded = safe_load(rendered)
        return bool(loaded)
    except Exception as e:
        logging.error(f"Failed to evaluate condition: {string}. Error: {e}")
        return False


async def extract_data(request: Request) -> dict[str, Any]:
    """Extract and parse data from the incoming request."""
    extracted_data: dict[str, Any] = {
        "json": None,
        "content": None,
        "form": None,
        "headers": dict(request.headers),
        "query": dict(request.query_params),
    }

    # Try to parse JSON data
    try:
        extracted_data["json"] = await request.json()
    except Exception as e:
        logging.debug(f"Failed to parse JSON: {e}")

    # Try to get raw content
    try:
        content = await request.body()
        if content:
            extracted_data["content"] = content.decode("utf-8")
    except Exception as e:
        logging.debug(f"Failed to get content: {e}")

    # Try to parse form data
    try:
        form_data = await request.form()
        if form_data:
            extracted_data["form"] = dict(form_data)
    except Exception as e:
        logging.debug(f"Failed to parse form data: {e}")

    return extracted_data


async def load_webhook_config() -> dict[str, Any]:
    """Load webhook configuration from YAML file."""
    config_file = Path(settings.config_path) / "webhooks.yml"

    if not config_file.exists():
        raise HTTPException(
            status_code=500, detail=f"Configuration file not found: {config_file}"
        )

    try:
        async with aiofiles.open(config_file, "r") as f:
            data = await f.read()
            return safe_load(data) or {}
    except Exception as e:
        logging.error(f"Failed to load config file {config_file}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to load configuration: {e}"
        ) from e


@app.post("/{webhook_id}")
async def webhook(webhook_id: str, request: Request) -> dict[str, str]:
    """Handle incoming webhook requests."""
    config = await load_webhook_config()

    if webhook_id not in config:
        logging.debug(f"{webhook_id} - Webhook not found in configuration")
        raise HTTPException(status_code=404, detail="Webhook not found")

    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")

    receivers = config[webhook_id]
    if not isinstance(receivers, list):
        raise HTTPException(
            status_code=500, detail="Invalid configuration: receivers must be a list"
        )

    logging.debug(f"{webhook_id} - Found {len(receivers)} receivers")

    template_env = await extract_data(request)
    successful_forwards = 0

    for receiver_config in receivers:
        if not isinstance(receiver_config, dict) or "url" not in receiver_config:
            logging.error(f"{webhook_id} - Invalid receiver config: {receiver_config}")
            continue

        if "json" in receiver_config and "body" in receiver_config:
            logging.error(
                f"{webhook_id} - Cannot specify both 'json' and 'body' in receiver config"
            )
            continue

        try:
            await process_receiver(webhook_id, receiver_config, template_env, request)
            successful_forwards += 1
        except Exception as e:
            logging.error(
                f"{webhook_id} - Failed to process receiver {receiver_config.get('url')}: {e}"
            )

    return {
        "status": "completed",
        "forwarded": str(successful_forwards),
        "total": str(len(receivers)),
    }


async def process_receiver(
    webhook_id: str,
    receiver_config: dict[str, Any],
    template_env: dict[str, Any],
    original_request: Request,
) -> None:
    """Process a single receiver configuration."""
    url = receiver_config["url"]

    # Prepare request content
    content: str | None = None
    if "json" in receiver_config:
        json_data = render_template_dict(receiver_config["json"], template_env)
        content = json.dumps(json_data)
    elif "body" in receiver_config:
        content = render_string(receiver_config["body"], template_env)

    # Prepare headers
    headers = prepare_headers(receiver_config, template_env, original_request)

    # Prepare form data
    form_data = None
    if "form" in receiver_config:
        form_data = render_template_dict(receiver_config["form"], template_env)

    # Check conditions
    if not check_conditions(receiver_config, template_env):
        logging.debug(f"{webhook_id} - Conditions not met for {url}")
        return

    # Send request
    method = receiver_config.get("method", "POST").upper()

    logging.debug(f"{webhook_id} - Sending {method} request to {url}")

    try:
        if not http_client:
            raise RuntimeError("HTTP client not initialized")

        response = await http_client.request(
            method=method,
            url=url,
            headers=headers,
            content=content,
            data=form_data,
        )
        response.raise_for_status()
        logging.debug(
            f"{webhook_id} - Successfully forwarded to {url} (status: {response.status_code})"
        )
    except httpx.HTTPError as e:
        logging.error(f"{webhook_id} - HTTP error forwarding to {url}: {e}")
        raise
    except Exception as e:
        logging.error(f"{webhook_id} - Unexpected error forwarding to {url}: {e}")
        raise


def render_template_dict(data: Any, template_env: dict[str, Any]) -> Any:
    """Recursively render template strings in a dictionary or list."""
    if isinstance(data, str):
        return render_string(data, template_env)
    elif isinstance(data, dict):
        return {
            key: render_template_dict(value, template_env)
            for key, value in data.items()
        }
    elif isinstance(data, list):
        return [render_template_dict(item, template_env) for item in data]
    else:
        return data


def prepare_headers(
    receiver_config: dict[str, Any],
    template_env: dict[str, Any],
    original_request: Request,
) -> dict[str, str]:
    """Prepare headers for the outgoing request."""
    headers = {}

    # Set default Content-Type if not specified
    if "json" in receiver_config:
        headers["Content-Type"] = "application/json"
    else:
        original_content_type = original_request.headers.get("Content-Type")
        if original_content_type:
            headers["Content-Type"] = original_content_type

    # Add custom headers
    if "headers" in receiver_config:
        custom_headers = render_template_dict(receiver_config["headers"], template_env)
        if isinstance(custom_headers, dict):
            headers.update(custom_headers)

    return headers


def check_conditions(
    receiver_config: dict[str, Any], template_env: dict[str, Any]
) -> bool:
    """Check if all conditions are met for this receiver."""
    conditions = receiver_config.get("conditions", [])

    for condition in conditions:
        if not evaluate_condition(condition, template_env):
            return False

    return True
