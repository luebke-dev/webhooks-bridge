import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from webhooks_bridge.main import app, settings
import tempfile


@pytest.fixture
def temp_config_dir():
    """Create a temporary config directory."""
    with tempfile.TemporaryDirectory() as temp_dir:
        old_config_path = settings.config_path
        settings.config_path = temp_dir
        yield temp_dir
        settings.config_path = old_config_path


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


@pytest.fixture
def sample_config(temp_config_dir):
    """Create a sample webhook configuration."""
    config_content = {
        "test-webhook": [
            {
                "url": "https://httpbin.org/post",
                "headers": {"X-Test-Header": "test-value"},
            }
        ],
        "test-webhook-with-conditions": [
            {
                "url": "https://httpbin.org/post",
                "conditions": [
                    "{% if json.test_field == 'test_value' %}True{% else %}False{% endif %}"
                ],
            }
        ],
    }

    config_file = Path(temp_config_dir) / "webhooks.yml"
    with open(config_file, "w") as f:
        import yaml

        yaml.dump(config_content, f)

    return config_content


def test_webhook_not_found(client, temp_config_dir):
    """Test webhook not found scenario."""
    # Create empty config
    config_file = Path(temp_config_dir) / "webhooks.yml"
    with open(config_file, "w") as f:
        f.write("{}")

    response = client.post("/non-existent-webhook", json={"test": "data"})
    assert response.status_code == 404


def test_config_file_missing(client, temp_config_dir):
    """Test missing config file."""
    response = client.post("/test-webhook", json={"test": "data"})
    assert response.status_code == 500


def test_template_rendering():
    """Test template rendering functionality."""
    from webhooks_bridge.main import render_string, render_template_dict

    template_env = {
        "json": {"name": "John", "age": 30},
        "headers": {"content-type": "application/json"},
    }

    # Test string rendering
    result = render_string("Hello {{ json.name }}", template_env)
    assert result == "Hello John"

    # Test dict rendering
    template_dict = {
        "user": "{{ json.name }}",
        "age": "{{ json.age }}",
        "nested": {"content_type": "{{ headers['content-type'] }}"},
    }

    result = render_template_dict(template_dict, template_env)
    expected = {
        "user": "John",
        "age": "30",
        "nested": {"content_type": "application/json"},
    }
    assert result == expected


def test_condition_evaluation():
    """Test condition evaluation."""
    from webhooks_bridge.main import evaluate_condition

    template_env = {"json": {"status": "active", "count": 5}}

    # Test true condition
    assert evaluate_condition(
        "{% if json.status == 'active' %}True{% else %}False{% endif %}", template_env
    )

    # Test false condition
    assert not evaluate_condition(
        "{% if json.count > 10 %}True{% else %}False{% endif %}", template_env
    )


def test_extract_data():
    """Test data extraction from request."""
    from webhooks_bridge.main import extract_data
    from fastapi import Request
    from unittest.mock import AsyncMock, MagicMock

    # Mock request
    request = MagicMock(spec=Request)
    request.json = AsyncMock(return_value={"test": "data"})
    request.body = AsyncMock(return_value=b'{"test": "data"}')
    request.form = AsyncMock(return_value={})
    request.headers = {"content-type": "application/json"}
    request.query_params = {"param": "value"}

    import asyncio

    async def test():
        data = await extract_data(request)
        assert data["json"] == {"test": "data"}
        assert data["content"] == '{"test": "data"}'
        assert data["headers"] == {"content-type": "application/json"}
        assert data["query"] == {"param": "value"}

    asyncio.run(test())


def test_prepare_headers():
    """Test header preparation."""
    from webhooks_bridge.main import prepare_headers
    from unittest.mock import MagicMock

    # Mock request with headers that behave like FastAPI headers
    class MockHeaders:
        def __init__(self, headers_dict):
            self._headers = headers_dict

        def get(self, key, default=None):
            # Case-insensitive header lookup
            for k, v in self._headers.items():
                if k.lower() == key.lower():
                    return v
            return default

    request = MagicMock()
    request.headers = MockHeaders({"content-type": "text/plain"})

    template_env = {"test": "value"}

    # Test with JSON content
    receiver_config = {"json": {"test": "data"}, "headers": {"X-Custom": "{{ test }}"}}

    headers = prepare_headers(receiver_config, template_env, request)
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Custom"] == "value"

    # Test with original content type preserved
    receiver_config = {"headers": {"X-Custom": "{{ test }}"}}

    headers = prepare_headers(receiver_config, template_env, request)
    assert headers.get("Content-Type") == "text/plain"
    assert headers["X-Custom"] == "value"


def test_check_conditions():
    """Test condition checking."""
    from webhooks_bridge.main import check_conditions

    template_env = {"json": {"status": "active"}}

    # Test with passing conditions
    receiver_config = {
        "conditions": ["{% if json.status == 'active' %}True{% else %}False{% endif %}"]
    }
    assert check_conditions(receiver_config, template_env)

    # Test with failing conditions
    receiver_config = {
        "conditions": [
            "{% if json.status == 'inactive' %}True{% else %}False{% endif %}"
        ]
    }
    assert not check_conditions(receiver_config, template_env)

    # Test with no conditions
    receiver_config = {}
    assert check_conditions(receiver_config, template_env)
