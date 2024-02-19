# ComfyUI Discord Bot

A simple and flexible discord bot that uses ComfyUI as a backend for content generation.

### Features

* Discord users can modify all parameters in basically any arbitrary workflow using simple syntax
* ComfyUI backend decoupled from the bot, so you can use your own local ComfyUI or remotely served

### Setup

1. Set up a python venv and install dependencies

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt

2. Visit https://discord.com/developers/applications and create a new discord bot application

3. Populate a `.env` file with the credentials from (2), or otherwise populate the required environment variables enumerated in `.env.example`

### Usage

    .dream start with the prompt --seed 1234 --NodeName.attribute newvalue

The `.dream` commands that any text it encouters prior to the first `--` it sees is the prompt. This is implicitly treated as if the user had provided a `--prompt` argument. 

The bot works by loading a default workflow and making changes to that workflow's json as needed per the user's requests. The user can target any node in the workflow using the `--NodeName.attribute newvalue` syntax. Alternatively, shorthand arguments can be specified in `special_args_map.json`, which default's to the following:

    {
      "prompt":{"node_name":"Prompt", "target_attr":"text"},
      "seed": {"node_name":"KSampler", "target_attr":"seed"}
    }

In other words, if a user provides a `--seed 0` argument, the bot will behave as if the user had specified the seed using the argument `--KSampler.seed 0`. This assumes that there is a node whose title is "KSampler". If your workflow has a KSampler node but the title is different, you'll need to update the `node_name` in the `special_args_map.json` to accomodate it. 

Similarly, by default, the bot assumes that the main prompt goes in a node named "Prompt". 

As a general rule: **nodes that could be targets for user intervention should use names with no spaces or special characters**. You can get around this by creating argument aliases in the `special_args_map.json`, but you're probably better off just naming your workflow nodes using **CamelCase** or some such.