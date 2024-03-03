
# TODO:
# * handle failed websocket connection
# * report errors back to user
# * maybe some special command attached to a workflow that just does something simple with the civit.ai nodes so people can download models
#   -  stuff like this should probably just be a different worker or somerthing

import os
import io
import random
import time

from dotenv import load_dotenv
from loguru import logger
import websocket

import discord
from discord.ext import commands

from discord_bot.mini_parser import parse_args
from comfy_utils.comfy_client import (
    get_outputs,
    server_address,
    client_id,
    comfy_is_ready,
    list_available_checkpoints,
    list_available_loras,
    get_model_zoo,
)
from comfy_utils.workflow_utils import (
    summarize_workflow,
    prep_workflow,
    set_node_by_title,
)

from comfy_utils.workflow_manager import WorkflowManager, Workflow
from comfy_utils.workflow_utils import API_WORKFLOW_NAME_PREFIX as api_prefix

from collections import Counter
import requests


load_dotenv()

application_id = os.environ.get('APPLICATION_ID')
public_key = os.environ.get('PUBLIC_KEY')
bot_user_token = os.environ.get('BOT_USER_TOKEN')

##############################################

# https://discordpy.readthedocs.io/en/stable/ext/commands/commands.html
# https://github.com/Rapptz/discord.py/blob/master/examples/basic_bot.py


intents = discord.Intents.default()
intents.message_content = True

description="i'm a bot."

bot = commands.Bot(command_prefix='.', description=description, intents=intents)


async def reboot_manager(bot, ctx):
    try:
        bot.workflow_mgr = WorkflowManager()
    except KeyError:
        logger.info("Default workflow not registered. Please register a 'default' workflow")
        await ctx.reply("Please register a 'default' workflow")

# to do: set bot status somewhere visible to the user
@bot.event
async def on_ready():
    logger.info(f'Logged in as {bot.user} (ID: {bot.user.id})')

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

    bot.workflow_mgr =None
    #reboot_manager(bot, ctx)
    try:
        bot.workflow_mgr = WorkflowManager()
        msg = "Bot is ready and connected to the ComfyUI backend."
        logger.info(msg)
        #await ctx.reply(msg)
    except KeyError:
        # TODO: i fno default registered, we should register a workflow that shipped with the code as default.
        # if we're feeling real fancy, we could update the workflow to default to a model that we know is registered
        # on the comfy instance
        logger.info(
            "Default workflow not registered. Please set a 'default' workflow by "
            "invoking `.register default` with the workflow attached."
        )

@bot.command()
async def reset(ctx, *, message=''):
    bot.workflow_mgr.active_workflow.reset()
    await ctx.reply("Workflow reset to its base state.")

@bot.command()
async def reset_hard(ctx, *, message=''):
    #bot.workflow_mgr.active_workflow.reset()
    await reboot_manager(bot, ctx)

async def register_from_attachment(ctx, workflow_name):
    workflow_url = ctx.message.attachments[0]
    response = requests.get(workflow_url)

    new_workflow = response.json()
    logger.info(new_workflow)
    logger.info(type(new_workflow))
    new_workflow = prep_workflow(new_workflow)

    if not workflow_name.startswith(api_prefix):
        workflow_name = api_prefix + workflow_name
    wf=Workflow(name=workflow_name, data=new_workflow)
    if bot.workflow_mgr is not None:
        bot.workflow_mgr.register(workflow=wf)
    else:
        wf.commit()
        reboot_manager(bot, ctx)

    outstr = summarize_workflow(new_workflow)
    await ctx.reply(f"```\n" + outstr + "\n```")

@bot.command()
async def register(ctx, *, message=''):
    if not message:
        await ctx.reply("Please provide a name to register the workflow to: `.register workflowName`")
    workflow_name = message
    if not workflow_name.startswith(api_prefix):
        workflow_name = api_prefix + workflow_name

    if ctx.message.attachments:
        await register_from_attachment(ctx, workflow_name)
    else:
        bot.workflow_mgr.register(name=workflow_name) # will use active workflow for data


def list_workflows_(bot):
    if bot.workflow_mgr is None:
        msg = (
            "No api workflows registered. "
            "Please provide a name to register the workflow to: `.register workflowName`"
        )
    else:
        workflows = bot.workflow_mgr.workflow_registry.keys()
        logger.info(list(workflows))
        workflows = [k[len(api_prefix):] for k in workflows if k.startswith(api_prefix)]
        workflows.sort()
        wf_str = "\n".join(list(workflows))
        msg = "Available registered workflows:\n```\n" + wf_str + "\n```\n"
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
        #answer = bot.workflow_mgr.workflow_registry.keys()
    await ctx.reply(answer)


@bot.command()
async def describe(ctx, *, message=''):
    header = f"Active workflow: **{bot.workflow_mgr.active_workflow.name[len(api_prefix):]}**"
    wf_descr = bot.workflow_mgr.active_workflow.summarize()
    outstr = header + "\n```\n" + wf_descr + "\n```"
    await ctx.reply(outstr)


# TODO: have this respond to the same arguments as .dream, so users can set persistent changes to the active workflow
@bot.command(name='set')
async def set_(ctx, *, message=''):
    workflow_name = message
    if not workflow_name:
        await ctx.reply(f"No workflow name provided. \n{list_workflows_(bot)}")
        return
    if not workflow_name.startswith(api_prefix):
        workflow_name = api_prefix + workflow_name
    try:
        bot.workflow_mgr.set_active(workflow_name)
        addendum = ""
        if bot.workflow_mgr.active_workflow._uncommitted_changes:
            addendum = (
                "\nNB: Workflow has uncommitted changes.\n"
                "* To roll-back to baseline, invoke the `.reset` command.\n"
                f"* To commit changes (overwriting the saved workflow named `{bot.workflow_mgr.active_workflow.name[len(api_prefix):]}`),"
                " invoke the `.register` command.\n"
                "* If you don't want to overwrite the saved workflow,"
                "pass a new name to register the active workflow to: `.register name`"
            )
        await ctx.reply(f"Active workflow switched to {workflow_name[len(api_prefix):]}.{addendum}")
    except KeyError:
        await ctx.reply(f"There's no workflow registered to the name {workflow_name[len(api_prefix):]}.\n{list_workflows_(bot)}")


# TODO: command to enable/disable automatic seed randomization
# TODO: add a validation function that checks workflow for loaders invoking unsupported models/loras
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
    await ctx.reply(str(simple_args))
                    
    workflow = bot.workflow_mgr.active_workflow
    if 'workflow' in args['other_args']:
        target_workflow = args['other_args']['workflow']
        if not target_workflow.startswith(api_prefix):
            target_workflow = api_prefix + target_workflow
        try:
            workflow = bot.workflow_mgr.workflow_registry[target_workflow]
            logger.info(f"temporarily using workflow {target_workflow}")
        except KeyError:
            await ctx.reply(
                f"There's no workflow registered to the name {target_workflow}. "
                f"\n{list_workflows_(bot)}"
                )
            return

    for k, rec in args['node_args'].items():
        workflow = set_node_by_title(workflow, rec['node_name'], rec['target_attr'], rec['value'])

    outputs = get_outputs(bot.ws_comfy, workflow.data)
    logger.debug(len(outputs))
    #im_data = list(images.values())[0][0]
    suffix_map = {'gifs':'mp4', 'images':'png'}
    for kind in outputs:
        for i, item in enumerate(outputs[kind]):
            #logger.info(item)
            out_name = f"{kind}_{i}.{suffix_map[kind]}"
            item_data = item #[0] #?
            logger.info(len(item_data))
            f = io.BytesIO(item_data)
            embed = discord.Embed()
            embed.set_image(url=f"attachment://{out_name}")
            await ctx.reply(str(simple_args), file=discord.File(f, out_name))
    #f = io.BytesIO(im_data)
    #logger.debug("pushed images to bytes object")

    #await ctx.reply(str(simple_args), file=discord.File(f, 'TEST.png'))

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