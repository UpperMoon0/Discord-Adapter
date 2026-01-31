# Lily-Discord-Adapter

Discord bot adapter for Lily-Core. This service connects Discord to the Lily-Core chatbot service.

## Features

- Discord bot integration with Lily-Core via WebSocket
- Text message processing
- Voice channel support (join/leave)
- Audio message handling
- Consul service discovery registration
- Health check endpoints

## Setup

### Prerequisites

- Python 3.11+
- Discord bot token
- Access to Lily-Core WebSocket endpoint

### Environment Variables

Create a `.env` file with the following variables:

```env
# Discord Configuration
DISCORD_BOT_TOKEN=your_discord_bot_token_here

# Lily-Core Configuration
LILY_CORE_URL=ws://lily-core:9002

# Service Configuration
PORT=8004

# Consul Configuration
CONSUL_HTTP_ADDR=consul:8500
```

### Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot
python main.py
```

### Docker

```bash
# Build the image
docker build -t nstut/lily-discord-adapter .

# Run the container
docker run -d \
  --name lily-discord-adapter \
  -p 8004:8004 \
  -e DISCORD_BOT_TOKEN=your_token \
  -e LILY_CORE_URL=ws://lily-core:9002 \
  -e CONSUL_HTTP_ADDR=consul:8500 \
  nstut/lily-discord-adapter
```

## Docker Compose

The service is configured in the main `compose.yaml` file. Start all services with:

```bash
docker compose up -d
```

## Bot Commands

- `!ping` - Check if the bot is alive
- `!lily <message>` - Send a message to Lily-Core
- `!join` - Join your voice channel
- `!leave` - Leave the current voice channel

## Architecture

```
┌─────────────┐     ┌──────────────────────┐     ┌─────────────┐
│   Discord   │────▶│ Lily-Discord-Adapter │────▶│  Lily-Core  │
│   Users     │◀────│   (WebSocket/HTTP)   │◀────│  (C++)      │
└─────────────┘     └──────────────────────┘     └─────────────┘
                            │
                            ▼
                    ┌─────────────┐
                    │   Consul    │
                    │ (Discovery) │
                    └─────────────┘
```

## Project Structure

```
Lily-Discord-Adapter/
├── Dockerfile
├── main.py
├── requirements.txt
├── .gitignore
├── README.md
└── utils/
    ├── __init__.py
    └── service_discovery.py
```
