
# TODO:
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
    print(f'loading workflow: {fpath}')
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

import requests


intents = discord.Intents.default()
intents.message_content = True

description="i'm a bot."

bot = commands.Bot(command_prefix='.', description=description, intents=intents)


# to do: set bot status somewhere visible to the user
@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user} (ID: {bot.user.id})')

    if not hasattr(bot, '_workflow_registry'):
        with open('workflow_registry.json') as f:
            bot._workflow_registry = json.load(f)
    if not hasattr(bot, '_base_workflow'):
        fpath = bot._workflow_registry['default']
        bot._base_workflow = load_workflow(fpath)
    
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

@bot.command()
async def reset(ctx, *, message=''):
    fpath = bot._workflow_registry['default']
    bot._base_workflow = load_workflow(fpath)
    await ctx.reply("Workflow reset to default workflow")

@bot.command()
async def register(ctx, *, message=''):
    workflow_name = message
    if not message:
        await ctx.reply("Please provide a name to register the workflow to: `.register workflowName`")
    elif not ctx.message.attachments:
        await ctx.reply("Please attach a workflow to set it as the new default workflow.")
    elif workflow_name in bot._workflow_registry:
        await ctx.reply(f"There's already a workflow registered to the name {workflow_name}. Please pick a different name.")
    else:
        
        workflow_url = ctx.message.attachments[0]
        response = requests.get(workflow_url)
        _, fname = response.headers['Content-Disposition'].split('filename=')
        fname = fname[1:-1] # remove quotes
        new_workflow = response.json()
        with open(fname) as f:
            json.dump(new_workflow)
        bot._workflow_registry[workflow_name] = fname

def list_workflows_(bot):
    padleft = "* `"
    padright = "`\n"
    msg = (
        f"Available registered workflows:\n{''.join([padleft+k+padright for k in bot._workflow_registry])}"
    )
    return msg

@bot.command()
async def list_workflows(ctx, *, message=''):
   await ctx.reply(list_workflows_(bot))

def get_workflow(bot,workflow_name):
    if workflow_name not in bot._workflow_registry:
        return copy.deepcopy(bot._base_workflow), False
    else:
        fpath = bot._workflow_registry[workflow_name]
        return load_workflow(fpath), True

@bot.command()
async def set_workflow(ctx, *, message=''):
    workflow_name = message
    new_workflow, is_new = get_workflow(workflow_name)
    if is_new:
        logger.info(f"new workflow:\n\n{new_workflow}\n\n")
        bot._base_workflow = new_workflow
        await ctx.reply("Default workflow updated.")
    else:
        await ctx.reply(f"There's no workflow registered to the name {workflow_name}.\n{list_workflows_(bot)}")

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
    if 'workflow' in args['other_args']:
        target_workflow = args['other_args']['workflow']
        workflow, success = get_workflow(bot, target_workflow)
        if success:
            logger.info(f"temporarily using workflow {target_workflow}")
        else:
            await ctx.reply(
                f"There's no workflow registered to the name {target_workflow}. "
                f"\n{list_workflows_(bot)}"
                )
            return

    for k, rec in args['node_args'].items():
        workflow = set_node_by_title(workflow, rec['node_name'], rec['target_attr'], rec['value'])
    logger.info(workflow)

    images = get_images(bot.ws_comfy, workflow)
    logger.debug(len(images))
    im_data = list(images.values())[0][0]
    f = io.BytesIO(im_data)
    logger.debug("pushed images to bytes object")

    await ctx.reply(str(simple_args), file=discord.File(f, 'TEST.png'))

bot.run(bot_user_token)