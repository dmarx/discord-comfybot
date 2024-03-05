# ComfyUI Discord Bot

A simple and flexible discord bot that uses ComfyUI as a backend for content generation.

NB: This tool is intended for private recreational use in small, private, carefully curated communities only. This bot gives your users a lot of power over the comfy environment and there's a high risk that malicious users could abuse this system to run arbitrary code on your ComfyUI server. You've been warned.


### Features

* Discord users can modify all parameters in basically any arbitrary workflow using simple syntax
* ComfyUI backend decoupled from the bot, so you can use your own local ComfyUI or remotely served


### Setup

1. Download the code

    $ git clone https://github.com/dmarx/discord-bot
    $ cd discord-bot

2. Set up a python venv

    $ python -m venv .venv
    $ source .venv/bin/activate

3. Install stuff

    $ pip install -r requirements.txt
    $ pip install ./comfy_utils
    $ pip install ./discord_bot

4. Visit https://discord.com/developers/applications and create a new discord bot application

3. Populate a `.env` file with the credentials from (2), or otherwise populate the required environment variables enumerated in `.env.example`

4. Start the bot

    $ discord-bot


### Usage

If the following list becomes out-of-date, running `.help` will pull the most recent docs directly from the bot.

Supported arguments:

* `.dream PROMPT [--NodeName.param value][--seed value]` - generate content using comfyui
* `.describe WORKFLOWNAME` - print a summary of a workflow to show available parameters and their default values
* `.register WORKFLOWNAME` - register a user-provided workflow
* `.set WORKFLOWNAME` - set the active workflow to a registered workflow
* `.reset` - revert active workflow to the server default
* `.list [models, loras]` - list registered workflows. can also be used to list available models and loras


#### `.dream PROMPT [--NodeName.param value][--seed value]`

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


#### `.describe WORKFLOWNAME`

If a workflow name is not provided, describes the current default.

```
CheckpointLoaderSimple - 'LoadCheckpoint'
  └── ckpt_name: SDXL-TURBO/sd_xl_turbo_1.0_fp16.safetensors

CLIPTextEncode - 'Prompt'
  └── text: yosemite national park

CLIPTextEncode - 'NegativePrompt'
  └── text: nsfw, nude, grotesque, confusing, crowded, mutated, fake, stupid, ugly, malformed, monochrome, saturated

KSampler - 'KSampler'
  ├── seed: 649762998076170
  ├── steps: 6
  ├── cfg: 1.8
  ├── sampler_name: lcm
  ├── scheduler: normal
  └── denoise: 1

EmptyLatentImage - 'EmptyLatent'
  ├── width: 768
  ├── height: 768
  └── batch_size: 1
```