
# TODO:
# * mechanism for registering/storing workflows
# * argument for invoking registered workflows
# * command to set/change current default workflow
# * handle failed websocket connection
# * report errors back to user

from dotenv import load_dotenv
import os
from loguru import logger

load_dotenv()

application_id = os.environ.get('APPLICATION_ID')
public_key = os.environ.get('PUBLIC_KEY')
bot_user_token = os.environ.get('BOT_USER_TOKEN')

##############################################

import copy
import json


def load_workflow(fpath="workflow_api.json"):
    print('loading workflow')
    with open(fpath) as f:
        return json.load(f)

def set_node_by_title(workflow, target_node, target_attr, value):
    workflow = copy.deepcopy(workflow)
    for node_id, node in workflow.items():
        if node['_meta']['title'] == target_node:
            node['inputs'][target_attr] = value
    return workflow

##############################################


# https://discordpy.readthedocs.io/en/stable/ext/commands/commands.html
# https://github.com/Rapptz/discord.py/blob/master/examples/basic_bot.py

import io
import random
import websocket
import time

import discord
from discord.ext import commands

from mini_parser import parse_args
from comfy_client import get_images, server_address, client_id, comfy_is_ready


intents = discord.Intents.default()
intents.message_content = True

description="i'm a bot."

bot = commands.Bot(command_prefix='.', description=description, intents=intents)

# to do: set bot status somewhere visible to the user
@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
    if not hasattr(bot, '_base_workflow'):
        bot._base_workflow = load_workflow()
    curr_wait = 5
    max_wait = 60
    while not comfy_is_ready():
        curr_wait*=2
        curr_wait = min(curr_wait, max_wait)
        logger.info(f"Unable to reach ComfyUI. Retrying in {curr_wait} seconds")
        time.sleep(curr_wait)
    if not hasattr(bot, 'ws_comfy'):
        ws = websocket.WebSocket()
        ws.connect("ws://{}/ws?clientId={}".format(server_address, client_id))
        bot.ws_comfy = ws
    logger.info("Bot is ready and connected to the ComfyUI backend.")

import requests

@bot.command()
async def set(ctx, *, message=''):
    if not ctx.message.attachments:
        await ctx.reply("Please attach a workflow to set it as the new default workflow.")
    else:
        logger.info(len(ctx.message.attachments))
        # TODO: workflow registration
        workflow_url = ctx.message.attachments[0]
        response = requests.get(workflow_url)
        new_workflow = response.json()
        logger.info(f"old workflow:\n\n{bot._base_workflow}\n\n")
        logger.info(f"new workflow:\n\n{new_workflow}\n\n")
        bot._base_workflow = new_workflow
        await ctx.reply("Default workflow updated.")

@bot.command()
async def dream(ctx, *, message=''):
    """dreams stuff."""
    logger.info(message)
    
    # kinda hacky but fuck it. i can change it later
    # need some mechanism to disable this per workflow. maybe only do this if
    # the workflow meets certain criteria. could also set workflow metadata in a Note node or something
    if ('--seed' not in message) and ('.seed' not in message):
        message += f" --seed {random.randint(0, 0xffffffffffffffff)}"
    args = parse_args(message)
    logger.info(args)
    # for reply
    simple_args = {k:v['value'] for k,v in args['node_args'].items()}

    workflow = copy.deepcopy(bot._base_workflow)
    for k, rec in args['node_args'].items():
        workflow = set_node_by_title(workflow, rec['node_name'], rec['target_attr'], rec['value'])
    logger.info(workflow)

    images = get_images(bot.ws_comfy, workflow)
    im_data = list(images.values())[0][0]
    f = io.BytesIO(im_data)

    await ctx.reply(str(simple_args), file=discord.File(f, 'TEST.png'))

bot.run(bot_user_token)