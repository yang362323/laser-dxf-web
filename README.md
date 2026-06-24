# feishu-laser-dxf-bot

A Feishu (Lark) chatbot that turns an image you send into a laser-ready DXF
file, using the [image-to-laser-dxf](https://github.com/yang362323/image-to-laser-dxf)
package. Reply includes a PNG preview, a one-line summary, and the DXF file.

## How it works

User sends a message containing the text `/dxf` and an image to a Feishu chat
where the bot is present. The bot:

1. Replies "正在处理..."
2. Downloads the image from Feishu
3. Runs `image_to_dxf.convert` to produce a DXF
4. Renders a PNG preview
5. Uploads both files
6. Sends a single rich-text (post) message with summary + preview + DXF

All conversion uses `image_to_dxf`'s defaults (`px_to_mm=0.05`, blur=5, ...).

## Feishu console setup (one-time)

1. Open https://open.feishu.cn/ and create a custom enterprise app.
2. Add the **Bot** capability.
3. Grant these permissions:
   - `im:message`
   - `im:message:send_as_bot`
   - `im:message.group_at_msg`
   - `im:message.p2p_msg`
   - `im:resource`
4. Under **Event Subscription**, register events so the bot can receive
   `im.message.receive_v1` (incoming messages). The lark-oapi WebSocket client
   receives these automatically once the app is published.
5. Copy the **App ID** and **App Secret** into `.env`.
6. In Feishu, search for the bot by name, open a chat, send a message.

Note: the slash command menu UI is configured in the Feishu console's "Bot
Features" page. When the user types `/` and selects `dxf`, the menu inserts
the `/dxf` text into the message box. The user then attaches an image and
hits send. The bot sees a normal `im.message.receive_v1` event whose
`message_type` is `image` and whose `content` starts with `/dxf`.

## Local development

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pip install -e ../image-to-laser-dxf
pytest -v
```

Smoke-test the health endpoint (uses fake creds; WS will fail to connect, but
the HTTP server still works):

```bash
FEISHU_APP_ID=cli_x FEISHU_APP_SECRET=y python -m app.main &
sleep 3
curl http://localhost:8080/healthz
kill %1
```

## Deploy

On the cloud server:

```bash
git clone <this-repo>
cd feishu-laser-dxf-bot
cp .env.example .env  # then edit .env with real App ID/Secret
docker compose up -d --build
docker compose logs -f bot
docker compose ps   # confirm healthcheck is "healthy"
```

The first build installs `image-to-laser-dxf` from the public GitHub repo
(pin via `ITD_REF` build arg in `docker-compose.yml`).

## Manual test checklist

- [ ] Private chat: send a message with `/dxf` and a simple JPG → receive DXF + preview
- [ ] Group chat: send a message with `/dxf` and an image → receive DXF + preview
- [ ] Send `/dxf` without an image → bot ignores (no error)
- [ ] Send a corrupt image → bot replies with an error message
- [ ] Two users in parallel → both succeed
- [ ] `docker compose restart bot` → bot reconnects to Feishu without intervention

## Layout

```
app/
  main.py            # entry point: lark WS + FastAPI /healthz
  config.py          # env-driven config
  handlers.py        # /dxf orchestrator
  feishu_client.py   # typed wrapper around lark SDK
  converter.py       # wraps image_to_dxf.convert
  preview.py         # DXF -> PNG rendering
tests/               # pytest suite
docs/superpowers/    # design spec + implementation plan
Dockerfile
docker-compose.yml
```

## License

MIT.
