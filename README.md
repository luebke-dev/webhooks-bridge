# Webhooks Bridge
A simple webhook receiver that filters, transforms and forwards webhooks.

## Install
### pip
```shell
pip install webhooks-bridge
WEBHOOKS_BRIDGE_CONFIG_PATH=$PWD uvicorn webhooks_bridge.main:app --port 8080
```
### Docker
```shell
export DATA_DIR=<YOUR_CONFIG_DIR>
docker run -p 8888:80 \
  --name webhooks-bridge \
  -e WEBHOOKS_BRIDGE_LOG_LEVEL=DEBUG \
  --mount type=bind,source=$DATA_DIR,target=/config \
  sebastiannoelluebke/webhooks-bridge:latest
```
## Usage

### Forward
By default the webhooks get forwarded with the original body and the same Content-Type.
```yaml
# webhooks.yml
my-cool-webhook: # POST http://localhost:8000/my-cool-webhook
  - url: "https://webhook-receiver-1/" 
  - url: "https://webhook-receiver-2/" # Forward to multiple receivers
```
### Filter
Use jinja2 templates to filter the incoming webhooks. If any of the conditions fails the webhook will not be forwarded. You can access the following data from the incoming request: ```json, headers, form, content(body), query```.
```yaml
# webhooks.yml
my-cool-webhook: # POST http://localhost:8000/my-cool-webhook
  - url: "https://webhook-receiver-3/api/webhook/SAHASDLITZENLXLHS"
    conditions:
      - "{% if json.NotificationUrl.object.Payment.alias.iban == 'DE123123123123213' %}True{% else %}False{% endif %}"
      - "{% if json.NotificationUrl.object.Payment.amount.value|float > 0 %}True{% else %}False{% endif %}"
```
### Transform
```yaml
# webhooks.yml
my-cool-webhook: # POST http://localhost:8000/my-cool-webhook
  - url: "https://webhook-receiver-1/"
    json:
      amount: "{{ json.NotificationUrl.object.Payment.amount.value }}"
      receiver: "{{ json.NotificationUrl.object.Payment.alias.iban }}"
      sender: "{{ json.NotificationUrl.object.Payment.counterparty_alias.iban }}"
      description: "{{ json.NotificationUrl.object.Payment.description }}"

```
### Custom headers
```yaml
# webhooks.yml
my-cool-webhook: # POST http://localhost:8000/my-cool-webhook
  - url: "https://webhook-receiver-1/"
    headers:
      x-customer-header: "my-header-value"
```
### All in one
```yaml
# webhooks.yml
my-cool-webhook: # POST http://localhost:8000/my-cool-webhook
  - url: "https://webhook-receiver-1/"
    headers:
      x-customer-header: "my-header-value"
    json:
      amount: "{{ json.NotificationUrl.object.Payment.amount.value }}"
      receiver: "{{ json.NotificationUrl.object.Payment.alias.iban }}"
      sender: "{{ json.NotificationUrl.object.Payment.counterparty_alias.iban }}"
      description: "{{ json.NotificationUrl.object.Payment.description }}"
      original_header: "{{ headers.x_my_header }}"
      query_param_1: "{{ query.param1 }}"
```
### Forward files
Currently it is not possible to forward webhooks with attached files
