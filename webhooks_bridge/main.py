import json
import logging

import aiofiles
import httpx
from fastapi import FastAPI, HTTPException, Request
from jinja2 import BaseLoader, Environment
from pydantic import BaseSettings
from yaml import safe_load


class Settings(BaseSettings):
    CONFIG_PATH: str | None = "/config/"
    LOG_LEVEL: str | None = "ERROR"

    class Config:
        env_prefix = "WEBHOOKS_BRIDGE_"


settings = Settings()
logging.basicConfig(
    filename=settings.CONFIG_PATH + "webhooks.log",
    encoding="utf-8",
    level=getattr(logging, settings.LOG_LEVEL.upper(), None),
)

app = FastAPI(title="Webhooks Bridge")


def render_string(string: str, values: dict) -> str | bool:
    template = Environment(loader=BaseLoader()).from_string(string)
    rendered = template.render(**values)
    return rendered


def evaluate_condition(string: str, values: dict) -> bool:
    string = render_string(string, values)
    loaded = safe_load(string)
    return loaded


async def extract_data(request: Request):
    try:
        json_data = await request.json()
    except:  # pylint: disable=E722
        json_data = None

    try:
        content = await request.body()
        content = content.decode("utf-8")
        if content == "":
            content = None
    except:
        content = None

    try:
        form_data = await request.form()
    except:
        form_data = None

    return {
        "json": json_data,
        "content": content,
        "form": form_data,
        "headers": request.headers,
        "query": request.query_params,
    }


@app.post("/{id}")
async def webhook(id: str, request: Request):
    async with aiofiles.open(settings.CONFIG_PATH + "webhooks.yml", "r") as f:
        data = await f.read()
        config = safe_load(data)

    if id in config:
        logging.debug(f"{id} - Found {len(config[id])} receivers")
        client = httpx.AsyncClient(verify=False)
        for item in config[id]:
            assert "url" in item
            assert not ("json" in item and "body" in item)

            content = None

            if "json" in item:
                content = json.dumps(item["json"])

            if "body" in item:
                content = item["body"]

            template_env = await extract_data(request)

            if "form" in item:
                for field in item["form"]:
                    item["form"][field] = render_string(
                        item["form"][field], template_env
                    )

            if "headers" in item:
                for header in item["headers"]:
                    item["headers"][header] = render_string(
                        item["headers"][header], template_env
                    )

            if content:
                content = render_string(content, template_env)

            send = True
            if "conditions" in item:
                for condition in item["conditions"]:
                    evaluated = evaluate_condition(condition, template_env)
                    logging.debug(
                        f"{id} - Condition: '{condition}' evaluated to {evaluated}"
                    )
                    if evaluated is False:
                        send = False
                        break

            if send:
                logging.debug(f"{id} - sending request to {item['url']}")
                await client.request(
                    method=item.get("method", "post"),
                    url=item["url"],
                    headers=item.get(
                        "headers", {"Content-Type": request.headers.get("Content-Type", "application/json")}
                    ),
                    content=content,
                    data=item.get("form", None),
                )
    else:
        logging.debug(f"{id} - Not found")
        raise HTTPException(status_code=404)
