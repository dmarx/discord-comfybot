"""
ComfyBot — Maubot plugin for ComfyUI image generation via Matrix.

Commands (prefix configurable in Maubot, default !):
  !dream <prompt> [--NodeName.attr value ...]   — generate an image
  !list [checkpoints|loras]                      — list workflows or models
  !describe                                      — describe active workflow
  !set <name>                                    — switch active workflow
  !register <name>                               — save active workflow as <name>
  !reset                                         — roll back active workflow to baseline

Workflow management (list/register/set) requires the pysssss custom node in ComfyUI.
Core generation (dream) uses only the standard ComfyUI API.

Fan-out: configure apprise_urls in plugin config to also post generated images
to Discord, Slack, etc. via Apprise after native Matrix delivery.
"""

import asyncio
import io
import json
import random
from typing import Optional, Type

import websocket
from loguru import logger
from maubot import Plugin, MessageEvent
from maubot.handlers import command
from mautrix.types import (
    ImageInfo,
    MediaMessageEventContent,
    MessageType,
    VideoInfo,
)
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper

from . import comfy_client as _cc
from .comfy_client import client_id, comfy_is_ready, get_outputs
from .comfy_client import list_available_checkpoints, list_available_loras
from .mini_parser import parse_args
from .notify import fan_out
from .workflow_manager import WorkflowManager
from .workflow_utils import API_WORKFLOW_NAME_PREFIX as api_prefix, set_node_by_title


class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("comfy_url")
        helper.copy("apprise_urls")


class ComfyBotPlugin(Plugin):
    workflow_mgr: Optional[WorkflowManager]
    ws_comfy: Optional[websocket.WebSocket]

    @classmethod
    def get_config_class(cls) -> Type[Config]:
        return Config

    async def on_start(self) -> None:
        self.config.load_and_update()
        self.workflow_mgr = None
        self.ws_comfy = None

        _cc.server_address = self.config["comfy_url"]
        logger.info(f"ComfyBot targeting ComfyUI at {_cc.server_address}")

        asyncio.get_event_loop().create_task(self._init_comfy())

    async def _init_comfy(self) -> None:
        loop = asyncio.get_event_loop()

        # Poll until ComfyUI is ready
        wait = 5
        while True:
            ready = await loop.run_in_executor(None, comfy_is_ready)
            if ready:
                break
            logger.info(f"ComfyUI not ready — retrying in {wait}s")
            await asyncio.sleep(wait)
            wait = min(wait * 2, 60)

        # Open persistent WebSocket for output streaming
        def _connect() -> websocket.WebSocket:
            ws = websocket.WebSocket()
            ws.connect(f"ws://{_cc.server_address}/ws?clientId={client_id}")
            return ws

        self.ws_comfy = await loop.run_in_executor(None, _connect)
        logger.info("ComfyUI WebSocket connected")

        # Build workflow registry (requires pysssss; skipped gracefully if absent)
        try:
            self.workflow_mgr = await loop.run_in_executor(None, WorkflowManager)
            logger.info("WorkflowManager ready")
        except Exception as e:
            logger.warning(
                f"WorkflowManager init failed ({e}). "
                "Workflow listing/switching unavailable; !dream still works with --workflow."
            )

    async def on_stop(self) -> None:
        if self.ws_comfy:
            try:
                self.ws_comfy.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _list_workflows_str(self) -> str:
        if not self.workflow_mgr:
            return "Workflow manager unavailable (pysssss not installed in ComfyUI)."
        workflows = sorted(
            k[len(api_prefix):]
            for k in self.workflow_mgr.workflow_registry
            if k.startswith(api_prefix)
        )
        if not workflows:
            return "No API workflows registered yet. Attach a workflow JSON and use `!register <name>`."
        return "Available workflows:\n```\n" + "\n".join(workflows) + "\n```"

    async def _post_outputs(self, evt: MessageEvent, outputs: dict, caption: str) -> None:
        """Upload ComfyUI outputs to Matrix then fan-out via Apprise."""
        kind_meta = {
            "images": ("image/png", ".png", MessageType.IMAGE),
            "gifs":   ("video/mp4", ".mp4", MessageType.VIDEO),
        }
        apprise_urls = self.config.get("apprise_urls", [])

        for kind, items in outputs.items():
            if kind not in kind_meta:
                continue
            mime, ext, msgtype = kind_meta[kind]
            for i, data in enumerate(items):
                filename = f"output_{i}{ext}"
                uri = await self.client.upload_media(data, mime_type=mime, filename=filename)
                content = MediaMessageEventContent(
                    msgtype=msgtype,
                    url=uri,
                    body=filename,
                )
                await evt.reply(content)

                if apprise_urls:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None, fan_out, apprise_urls, "ComfyUI output", caption, data, mime
                    )

    # ------------------------------------------------------------------ #
    # Commands
    # ------------------------------------------------------------------ #

    @command.new("dream", help="Generate an image. Usage: !dream <prompt> [--NodeName.attr value ...]")
    @command.argument("args", pass_raw=True, required=False)
    async def dream_handler(self, evt: MessageEvent, args: str = "") -> None:
        if not args:
            await evt.reply("Usage: `!dream <prompt> [--NodeName.attr value ...]`")
            return
        if not self.ws_comfy:
            await evt.reply("ComfyUI not connected yet — please wait a moment and try again.")
            return

        if "--seed" not in args:
            args += f" --seed {random.randint(0, 0xFFFF_FFFF_FFFF_FFFF)}"

        parsed = parse_args(args)
        simple_args = {k: v["value"] for k, v in parsed["node_args"].items()}
        await evt.reply(f"Queuing: `{simple_args}`")

        # Resolve which workflow to use
        if self.workflow_mgr:
            workflow = self.workflow_mgr.active_workflow
        else:
            await evt.reply("No workflow manager — cannot resolve a workflow. Register one first.")
            return

        if "workflow" in parsed["other_args"]:
            target = parsed["other_args"]["workflow"]
            if not target.startswith(api_prefix):
                target = api_prefix + target
            try:
                workflow = self.workflow_mgr.workflow_registry[target]
            except KeyError:
                await evt.reply(
                    f"Unknown workflow: `{target[len(api_prefix):]}`\n{self._list_workflows_str()}"
                )
                return

        for rec in parsed["node_args"].values():
            workflow = set_node_by_title(workflow, rec["node_name"], rec["target_attr"], rec["value"])

        loop = asyncio.get_event_loop()
        try:
            outputs = await loop.run_in_executor(None, get_outputs, self.ws_comfy, dict(workflow))
        except Exception as e:
            await evt.reply(f"ComfyUI error: {e}")
            return

        if not outputs:
            await evt.reply("ComfyUI finished but produced no outputs.")
            return

        await self._post_outputs(evt, outputs, str(simple_args))

    @command.new("list", help="List workflows, checkpoints, or loras. Usage: !list [checkpoints|loras]")
    @command.argument("what", required=False)
    async def list_handler(self, evt: MessageEvent, what: str = "") -> None:
        loop = asyncio.get_event_loop()
        if what in ("models", "checkpoints"):
            try:
                result = await loop.run_in_executor(None, list_available_checkpoints)
                names = result[0] if isinstance(result, (list, tuple)) and result else []
                await evt.reply("**Checkpoints:**\n```\n" + "\n".join(names) + "\n```")
            except Exception as e:
                await evt.reply(f"Could not fetch checkpoints: {e}")
        elif what == "loras":
            try:
                result = await loop.run_in_executor(None, list_available_loras)
                names = result[0] if isinstance(result, (list, tuple)) and result else []
                await evt.reply("**LoRAs:**\n```\n" + "\n".join(names) + "\n```")
            except Exception as e:
                await evt.reply(f"Could not fetch LoRAs: {e}")
        else:
            await evt.reply(self._list_workflows_str())

    @command.new("describe", help="Describe the currently active workflow")
    async def describe_handler(self, evt: MessageEvent) -> None:
        if not self.workflow_mgr:
            await evt.reply("Workflow manager unavailable.")
            return
        wf = self.workflow_mgr.active_workflow
        name = wf.name[len(api_prefix):]
        summary = wf.summarize()
        await evt.reply(f"**Active workflow: {name}**\n```\n{summary}\n```")

    @command.new("set", help="Switch the active workflow. Usage: !set <name>")
    @command.argument("name", required=True)
    async def set_handler(self, evt: MessageEvent, name: str) -> None:
        if not self.workflow_mgr:
            await evt.reply("Workflow manager unavailable.")
            return
        if not name.startswith(api_prefix):
            name = api_prefix + name
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.workflow_mgr.set_active, name)
            await evt.reply(f"Active workflow: `{name[len(api_prefix):]}`")
        except KeyError:
            await evt.reply(
                f"No workflow named `{name[len(api_prefix):]}`.\n{self._list_workflows_str()}"
            )

    @command.new("register", help="Save the active workflow under a new name. Usage: !register <name>")
    @command.argument("name", required=True)
    async def register_handler(self, evt: MessageEvent, name: str) -> None:
        if not self.workflow_mgr:
            await evt.reply("Workflow manager unavailable (pysssss not installed in ComfyUI).")
            return
        if not name.startswith(api_prefix):
            name = api_prefix + name
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.workflow_mgr.register, name)
            await evt.reply(f"Registered active workflow as `{name[len(api_prefix):]}`.")
        except Exception as e:
            await evt.reply(f"Registration failed: {e}")

    @command.new("reset", help="Roll back the active workflow to its saved baseline")
    async def reset_handler(self, evt: MessageEvent) -> None:
        if not self.workflow_mgr:
            await evt.reply("Workflow manager unavailable.")
            return
        self.workflow_mgr.active_workflow.reset()
        await evt.reply("Workflow reset to baseline.")
