# ComfyUI Discord Bot

A simple and flexible discord bot that uses ComfyUI as a backend for content generation.

### Setup

1. Set up a python venv and install dependencies

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

2. Visit https://discord.com/developers/applications and create a new discord bot application

3. Populate a `.env` file with the credentials from (2), or otherwise populate the required environment variables enumerated in `.env.example`