
# TODO:
# * handle failed websocket connection
# * report errors back to user
# * make workflow registry persistent
#   - need to update the registry .json
#   - even simpler: just have a fucking dedicated folder
# * .set for updating values in the active workflow
# * .save/.commit/.whatever to update the registry with the current settings
#    - should also have the option to save to a new name
#    - feels like a lot of what i'm doing here is "workflow management"
# * maybe some special command attached to a workflow that just does something simple with the civit.ai nodes so people can download models
#   -  stuff like this should probably just be a different worker or somerthing

from dotenv import load_dotenv
import os
from loguru import logger

import copy
import json


import io
import random
import websocket
import time
import string

import discord
from discord.ext import commands

from mini_parser import parse_args
from comfy_client import (
    get_images,
    server_address,
    client_id,
    comfy_is_ready,
    list_available_checkpoints,
    list_available_loras,
    #restart_comfy,
    get_model_zoo,
    #################
    fetch_saved_workflow,
    list_saved_workflows,
    fetch_saved_workflow,
)
from workflow_utils import (
    summarize_workflow,
    prep_workflow,

)

from collections import Counter, UserDict
from dataclasses import dataclass
import requests


load_dotenv()

application_id = os.environ.get('APPLICATION_ID')
public_key = os.environ.get('PUBLIC_KEY')
bot_user_token = os.environ.get('BOT_USER_TOKEN')

##############################################

from typing import Dict, List, Union, Optional

class Workflow(UserDict):
    # TODO: validate api confmity on init
    def __str__(self):
        return json.dumps(self)

@dataclass
class BotDB:
    workflow_registry: Dict[str, Workflow | None ] # {name, workflow}
    default_workflow_name: str = 'default'
    active_workflow: Workflow = None
    active_workflow_has_uncommitted_changes:bool = False


##############################################

def load_workflow(fpath="workflow_api.json"):
    logger.info(f'loading workflow: {fpath}')
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


intents = discord.Intents.default()
intents.message_content = True

description="i'm a bot."

bot = commands.Bot(command_prefix='.', description=description, intents=intents)

# to do: set bot status somewhere visible to the user
@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user} (ID: {bot.user.id})')


    def refresh_workflow_registry(bot):
        if not hasattr(bot, '_workflow_registry'):
            with open('workflow_registry.json') as f:
                bot._workflow_registry = json.load(f)
        #return bot

    def init_load_default_workflow(bot):
        if not hasattr(bot, '_base_workflow'):
            fpath = bot._workflow_registry['default']
            bot._base_workflow = load_workflow(fpath) # Todo: add a variable tracking the name of the current workflow for save/overwrite
        #return bot


    refresh_workflow_registry(bot)  # todo: get from server
    init_load_default_workflow(bot) # todo: 1. prefer from server. 2.1 else fetch local workflow per env var 2.2 save to server
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
        #_, fname = response.headers['Content-Disposition'].split('filename=')
        #fname = fname[1:-1] # remove quotes
        fname = f"{workflow_name}.json"
        new_workflow = response.json()
        new_workflow = prep_workflow(new_workflow)
        with open(fname, 'w') as f:
            json.dump(new_workflow, f)
        bot._workflow_registry[workflow_name] = fname

        outstr = summarize_workflow(new_workflow)
        await ctx.reply(outstr)


def list_workflows_(bot):
    padleft = "* `"
    padright = "`\n"
    #bot._workflow_registry
    newline = "\n"
    msg = (
        f"Available registered workflows:{newline}```{newline.join(list_saved_workflows())}{newline}```"
    )
    return msg


@bot.command(name='list')
async def list_(ctx, *, message=''):
    if message in ('models', 'checkpoints'):
        answer = list_available_checkpoints()
    elif message == 'loras':
        answer = list_available_loras()
    elif message.startswith('zoo'): # todo: let user query installed from zoo
        kind = None
        if ' ' in message:
            _, kind = message.split()
            kind = kind.strip()
        zoo = get_model_zoo()
        cnt = Counter()
        answer = "base | name"
        for rec in zoo['models']:
            if (rec['installed'] != 'True'):
                cnt[rec['type']] +=1
                if  (rec['type'] == kind):
                    answer += f"\n {rec['base']} \t {rec['name']}"
        if '\n' not in answer:
            answer = '\n'.join([f"{k}: {v}" for k,v in cnt.items()])
    else:
        answer = list_workflows_(bot)
    await ctx.reply(answer)


def get_workflow(bot,workflow_name):
    if workflow_name not in bot._workflow_registry:
        return copy.deepcopy(bot._base_workflow), False
    else:
        fpath = bot._workflow_registry[workflow_name]
        return load_workflow(fpath), True


@bot.command()
async def describe(ctx, *, message=''):
    w,_ = get_workflow(bot, message)
    #w = fetch_saved_workflow(message)
    outstr = summarize_workflow(w)
    await ctx.reply(f"```{outstr}\n```")


@bot.command(name='set')
async def set_(ctx, *, message=''):
    workflow_name = message
    if not workflow_name:
        await ctx.reply(f"No workflow name provided. \n{list_workflows_(bot)}")
        return
    new_workflow, is_new = get_workflow(bot, workflow_name)
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

#from http.client import RemoteDisconnected

# @bot.command()
# async def reboot(ctx, *, message=''):
#     #logger.info("closing websocket")
#     #bot.ws_comfy.close() # discord really disliked that. i'm wondering if maybe... the websocket connections are shared or something?
#     try:
#         restart_comfy() # kills the websocket connection
#     except Exception as e:
#         logger.info(type(e))
#         #logger.info("Comfy restarting...")
#     #except (ConnectionRefusedError, requests.exceptions.ConnectionError):    
#     await on_ready()


bot.run(bot_user_token)