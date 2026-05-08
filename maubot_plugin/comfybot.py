"""
ComfyBot — Maubot plugin for ComfyUI image generation via Matrix.

All helper code is inlined (single-file plugin) to avoid Maubot zip-importer
compatibility issues with package subdirectories.

Commands (default prefix !):
  !dream <prompt> [--NodeName.attr value ...]  — generate an image
  !list [checkpoints|loras]                    — list workflows or models
  !describe                                    — describe active workflow
  !set <name>                                  — switch active workflow
  !register <name>                             — save active workflow
  !reset                                       — roll back to baseline

Workflow management requires the pysssss custom node in ComfyUI.
Core generation (!dream) uses only the standard ComfyUI API.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import random
import string
import tempfile
import urllib.parse
import urllib.request
import uuid
from collections import UserDict
from copy import deepcopy
from pathlib import Path
from typing import Optional, Type

import requests
import websocket
from loguru import logger
from maubot import Plugin, MessageEvent
from maubot.handlers import command
from mautrix.types import MediaMessageEventContent, MessageType
from mautrix.util.config import BaseProxyConfig, ConfigUpdateHelper

# ---------------------------------------------------------------------------
# workflow_utils (inlined)
# ---------------------------------------------------------------------------
API_WORKFLOW_NAME_PREFIX = '_api_'


def _set_node_by_title(workflow, target_node, target_attr, value):
    for node_id, node in workflow.items():
        node = copy.deepcopy(node)
        if node['_meta']['title'] == target_node:
            node['inputs'][target_attr] = value
            workflow[node_id] = node
    return workflow


def _summarize_workflow(workflow):
    outstr = ''
    for v in workflow.values():
        recs = [(p, q) for p, q in v['inputs'].items() if not isinstance(q, list)]
        if not recs:
            continue
        outstr += f"{v['class_type']} - '{v['_meta']['title']}'\n"
        for i, (k, val) in enumerate(recs):
            pad = "├──" if i < len(recs) - 1 else "└──"
            outstr += f"  {pad} {k}: {val}\n"
        outstr += "\n"
    return outstr


def _sanitize_title(title):
    title = title.strip()
    for g in string.punctuation:
        if g not in ('_', '-'):
            title = title.replace(g, ' ')
    title = title.title().replace(' ', '')
    return title


def _prep_workflow(workflow):
    titles: set = set()
    for v in workflow.values():
        t = _sanitize_title(v['_meta']['title'])
        while t in titles:
            t += '-'
        titles.add(t)
        v['_meta']['title'] = t
    for v in workflow.values():
        t = v['_meta']['title']
        n = 0
        while t.endswith('-'):
            t = t[:-1]
            n += 1
        if n:
            t += str(n + 1)
        v['_meta']['title'] = t
    return workflow


# ---------------------------------------------------------------------------
# comfy_client (inlined)
# ---------------------------------------------------------------------------
_server_address = os.environ.get('COMFY_URL', 'localhost:8188')
_client_id = str(uuid.uuid4())


def _comfy_is_ready() -> bool:
    try:
        r = requests.get(f"http://{_server_address}/queue", timeout=5)
        return r.status_code == 200
    except requests.exceptions.RequestException:
        return False


def _get_object_info():
    return requests.get(f"http://{_server_address}/object_info").json()


def _list_checkpoints():
    return _get_object_info().get('CheckpointLoaderSimple', {}).get('input', {}).get(
        'required', {}).get('ckpt_name', [[]])[0]


def _list_loras():
    return _get_object_info().get('LoraLoader', {}).get('input', {}).get(
        'required', {}).get('lora_name', [[]])[0]


def _list_saved_workflows(api_only=False):
    """Requires pysssss custom node."""
    r = requests.get(f"http://{_server_address}/pysssss/workflows")
    r.raise_for_status()
    names = sorted(r.json())
    if api_only:
        names = [n for n in names if n.startswith(API_WORKFLOW_NAME_PREFIX)]
    return names


def _fetch_saved_workflow(name):
    from urllib.parse import quote
    r = requests.get(f"http://{_server_address}/pysssss/workflows/{quote(name)}")
    r.raise_for_status()
    return r.json()


def _save_workflow(name, workflow):
    payload = json.dumps({'name': name, 'workflow': workflow})
    return requests.post(f"http://{_server_address}/pysssss/workflows", data=payload)


def _queue_prompt(prompt):
    data = json.dumps({"prompt": prompt, "client_id": _client_id}).encode()
    req = urllib.request.Request(f"http://{_server_address}/prompt", data=data)
    return json.loads(urllib.request.urlopen(req).read())


def _get_output(filename, subfolder, folder_type):
    params = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": folder_type})
    with urllib.request.urlopen(f"http://{_server_address}/view?{params}") as resp:
        return resp.read()


def _get_history(prompt_id):
    with urllib.request.urlopen(f"http://{_server_address}/history/{prompt_id}") as resp:
        return json.loads(resp.read())


def _get_outputs(ws: websocket.WebSocket, prompt: dict) -> dict:
    prompt_id = _queue_prompt(prompt)['prompt_id']
    while True:
        out = ws.recv()
        if isinstance(out, str):
            msg = json.loads(out)
            if msg['type'] == 'executing':
                d = msg['data']
                if d['node'] is None and d['prompt_id'] == prompt_id:
                    break
    history = _get_history(prompt_id)[prompt_id]
    all_outputs: dict = {}
    for node_id in history['outputs']:
        node_out = history['outputs'][node_id]
        for kind in ('gifs', 'images'):
            if kind in node_out:
                items = [_get_output(o['filename'], o['subfolder'], o['type'])
                         for o in node_out[kind]]
                if items:
                    all_outputs.setdefault(kind, []).extend(items)
    return all_outputs


# ---------------------------------------------------------------------------
# workflow_manager (inlined)
# ---------------------------------------------------------------------------
class _Workflow(UserDict):
    def __init__(self, name: str, data: dict = None):
        self.name = name
        self._data = data or {}
        self._baseline = deepcopy(self._data)
        self._uncommitted_changes = False

    @property
    def data(self):
        if not self._data:
            self._fetch()
        return self._data

    def reset(self):
        self._data = deepcopy(self._baseline)
        self._uncommitted_changes = False

    def commit(self):
        _save_workflow(self.name, self.data)
        self._baseline = deepcopy(self.data)
        self._uncommitted_changes = False

    def summarize(self):
        return _summarize_workflow(self.data)

    def _fetch(self):
        data = _fetch_saved_workflow(self.name)
        self._data = data
        if not self._baseline:
            self._baseline = deepcopy(data)

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v_new):
        if self.data.get(k) != v_new:
            self.data[k] = v_new
            self._uncommitted_changes = True

    def __str__(self):
        return json.dumps(self.data)


class _WorkflowManager:
    def __init__(self, default_name=f"{API_WORKFLOW_NAME_PREFIX}default"):
        self.workflow_registry: dict[str, _Workflow] = {}
        self.default_workflow_name = default_name
        self._refresh()
        self._set_active(None)

    def _refresh(self):
        self.workflow_registry = {
            n: _Workflow(name=n) for n in _list_saved_workflows(api_only=True)
        }

    def _set_active(self, name):
        if name is None:
            name = os.environ.get('COMFYCLI_ACTIVE_WORKFLOW', self.default_workflow_name)
        if name not in self.workflow_registry:
            self._refresh()
        if name not in self.workflow_registry:
            raise KeyError(f"No workflow named {name!r}")
        self._active = name

    @property
    def active_workflow(self) -> _Workflow:
        return self.workflow_registry[self._active]

    def set_active(self, name):
        self._set_active(name)

    def register(self, name=None, workflow: _Workflow = None):
        wf = deepcopy(workflow or self.active_workflow)
        if name:
            wf.name = name
        wf.commit()
        self.workflow_registry[wf.name] = wf

    def reset_active(self):
        self.active_workflow.reset()


# ---------------------------------------------------------------------------
# mini_parser (inlined)
# ---------------------------------------------------------------------------
_SPECIAL_ARGS = {
    "prompt": {"node_name": "Prompt",   "target_attr": "text"},
    "seed":   {"node_name": "Ksampler", "target_attr": "seed"},
}


def _parse_arg_name(argname):
    if '.' not in argname:
        return _SPECIAL_ARGS.get(argname, False)
    node, attr = argname.split('.', 1)
    return {'node_name': node, 'target_attr': attr}


def _parse_args(in_str: str) -> dict:
    args: dict = {}
    parts = in_str.split('--', maxsplit=1)
    prompt = parts[0] if isinstance(parts[0], str) else parts[0][0]
    args['prompt'] = prompt
    if len(parts) > 1:
        for chunk in f"--{parts[1]}".split('--'):
            chunk = chunk.strip()
            if not chunk:
                continue
            if ' ' not in chunk:
                args[chunk] = True
            else:
                k, v = chunk.split(' ', maxsplit=1)
                args[k] = v.strip() or True
    node_args, other_args = {}, {}
    for k, v in args.items():
        rec = _parse_arg_name(k)
        if rec:
            node_args[k] = {**rec, 'value': v}
        else:
            other_args[k] = v
    return {'node_args': node_args, 'other_args': other_args}


# ---------------------------------------------------------------------------
# Default minimal txt2img workflow (fallback when pysssss / WorkflowManager
# is unavailable).  Checkpoint is filled in at runtime from the first entry
# returned by /object_info.
# ---------------------------------------------------------------------------
_DEFAULT_WORKFLOW_TEMPLATE = {
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "_meta": {"title": "CheckpointLoader"},
        "inputs": {"ckpt_name": "__CHECKPOINT__"},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "_meta": {"title": "Prompt"},
        "inputs": {"text": "beautiful landscape", "clip": ["4", 1]},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "_meta": {"title": "NegativePrompt"},
        "inputs": {"text": "blurry, ugly, deformed, low quality", "clip": ["4", 1]},
    },
    "3": {
        "class_type": "KSampler",
        "_meta": {"title": "Ksampler"},
        "inputs": {
            "seed": 0,
            "steps": 20,
            "cfg": 7.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0],
        },
    },
    "5": {
        "class_type": "EmptyLatentImage",
        "_meta": {"title": "EmptyLatentImage"},
        "inputs": {"width": 512, "height": 512, "batch_size": 1},
    },
    "8": {
        "class_type": "VAEDecode",
        "_meta": {"title": "VAEDecode"},
        "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
    },
    "9": {
        "class_type": "SaveImage",
        "_meta": {"title": "SaveImage"},
        "inputs": {"filename_prefix": "maubot", "images": ["8", 0]},
    },
}


# ---------------------------------------------------------------------------
# notify (inlined)
# ---------------------------------------------------------------------------
def _fan_out(urls: list, title: str, body: str, image_data: bytes = None, mime: str = "image/png"):
    if not urls:
        return
    try:
        import apprise
    except ImportError:
        logger.warning("apprise not installed — skipping fan-out")
        return
    ap = apprise.Apprise()
    for url in urls:
        ap.add(url)
    attach = None
    tmp_path = None
    if image_data:
        suffix = ".mp4" if "mp4" in mime or "video" in mime else ".png"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp.write(image_data)
        tmp.close()
        tmp_path = tmp.name
        attach = apprise.AppriseAttachment()
        attach.add(tmp_path)
    try:
        ap.notify(title=title, body=body, attach=attach)
    except Exception as e:
        logger.warning(f"Apprise fan-out failed: {e}")
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Plugin
# ---------------------------------------------------------------------------
class Config(BaseProxyConfig):
    def do_update(self, helper: ConfigUpdateHelper) -> None:
        helper.copy("comfy_url")
        helper.copy("apprise_urls")


class ComfyBotPlugin(Plugin):
    workflow_mgr: Optional[_WorkflowManager] = None
    ws_comfy: Optional[websocket.WebSocket] = None

    @classmethod
    def get_config_class(cls) -> Type[Config]:
        return Config

    async def start(self) -> None:
        self.workflow_mgr = None
        self.ws_comfy = None
        try:
            self.config.load_and_update()
        except Exception as e:
            self.log.error(f"ComfyBot config load failed: {e}")
        global _server_address
        try:
            _server_address = self.config["comfy_url"]
        except Exception as e:
            self.log.error(f"ComfyBot could not read comfy_url from config: {e}")
        self.log.info(f"ComfyBot targeting ComfyUI at {_server_address}")
        asyncio.get_event_loop().create_task(self._init_comfy())

    async def stop(self) -> None:
        if self.ws_comfy:
            try:
                self.ws_comfy.close()
            except Exception:
                pass

    async def _init_comfy(self) -> None:
        loop = asyncio.get_event_loop()
        wait = 5
        while True:
            ready = await loop.run_in_executor(None, _comfy_is_ready)
            if ready:
                break
            self.log.info(f"ComfyUI not ready — retrying in {wait}s")
            await asyncio.sleep(wait)
            wait = min(wait * 2, 60)

        def _connect():
            ws = websocket.WebSocket()
            ws.connect(f"ws://{_server_address}/ws?clientId={_client_id}")
            return ws

        self.ws_comfy = await loop.run_in_executor(None, _connect)
        self.log.info("ComfyUI WebSocket connected")

        try:
            self.workflow_mgr = await loop.run_in_executor(None, _WorkflowManager)
            self.log.info("WorkflowManager ready")
        except Exception as e:
            self.log.warning(f"WorkflowManager unavailable ({e}) — !dream uses fallback workflow")

    def _list_str(self) -> str:
        if not self.workflow_mgr:
            return "Workflow manager unavailable (pysssss not installed in ComfyUI)."
        names = sorted(
            k[len(API_WORKFLOW_NAME_PREFIX):]
            for k in self.workflow_mgr.workflow_registry
            if k.startswith(API_WORKFLOW_NAME_PREFIX)
        )
        if not names:
            return "No API workflows registered yet."
        return "Available workflows:\n```\n" + "\n".join(names) + "\n```"

    async def _post_outputs(self, evt: MessageEvent, outputs: dict, caption: str) -> None:
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
                await evt.reply(MediaMessageEventContent(msgtype=msgtype, url=uri, body=filename))
                if apprise_urls:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, _fan_out, apprise_urls, "ComfyUI output", caption, data, mime)

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
        parsed = _parse_args(args)
        simple = {k: v["value"] for k, v in parsed["node_args"].items()}

        loop = asyncio.get_event_loop()

        if self.workflow_mgr:
            workflow = self.workflow_mgr.active_workflow
            if "workflow" in parsed["other_args"]:
                target = parsed["other_args"]["workflow"]
                if not target.startswith(API_WORKFLOW_NAME_PREFIX):
                    target = API_WORKFLOW_NAME_PREFIX + target
                try:
                    workflow = self.workflow_mgr.workflow_registry[target]
                except KeyError:
                    await evt.reply(f"Unknown workflow: `{target[len(API_WORKFLOW_NAME_PREFIX):]}`\n{self._list_str()}")
                    return
            workflow = dict(workflow)
        else:
            # No pysssss — build a minimal workflow from the first available checkpoint
            try:
                checkpoints = await loop.run_in_executor(None, _list_checkpoints)
            except Exception as e:
                await evt.reply(f"Could not query ComfyUI checkpoints: {e}")
                return
            if not checkpoints:
                await evt.reply("No checkpoints found in ComfyUI. Please add a model checkpoint.")
                return
            checkpoint = checkpoints[0]
            workflow = deepcopy(_DEFAULT_WORKFLOW_TEMPLATE)
            workflow["4"]["inputs"]["ckpt_name"] = checkpoint
            await evt.reply(f"_(using default workflow with `{checkpoint}`)_")

        for rec in parsed["node_args"].values():
            workflow = _set_node_by_title(workflow, rec["node_name"], rec["target_attr"], rec["value"])

        await evt.reply(f"Queuing: `{simple}`")
        try:
            outputs = await loop.run_in_executor(None, _get_outputs, self.ws_comfy, workflow)
        except Exception as e:
            await evt.reply(f"ComfyUI error: {e}")
            return
        if not outputs:
            await evt.reply("ComfyUI finished but produced no outputs.")
            return
        await self._post_outputs(evt, outputs, str(simple))

    @command.new("list", help="List workflows, checkpoints, or loras")
    @command.argument("what", required=False)
    async def list_handler(self, evt: MessageEvent, what: str = "") -> None:
        loop = asyncio.get_event_loop()
        if what in ("models", "checkpoints"):
            try:
                names = await loop.run_in_executor(None, _list_checkpoints)
                await evt.reply("**Checkpoints:**\n```\n" + "\n".join(names) + "\n```")
            except Exception as e:
                await evt.reply(f"Could not fetch checkpoints: {e}")
        elif what == "loras":
            try:
                names = await loop.run_in_executor(None, _list_loras)
                await evt.reply("**LoRAs:**\n```\n" + "\n".join(names) + "\n```")
            except Exception as e:
                await evt.reply(f"Could not fetch LoRAs: {e}")
        else:
            await evt.reply(self._list_str())

    @command.new("describe", help="Describe the active workflow")
    async def describe_handler(self, evt: MessageEvent) -> None:
        if not self.workflow_mgr:
            await evt.reply("Workflow manager unavailable.")
            return
        wf = self.workflow_mgr.active_workflow
        name = wf.name[len(API_WORKFLOW_NAME_PREFIX):]
        await evt.reply(f"**Active workflow: {name}**\n```\n{wf.summarize()}\n```")

    @command.new("set", help="Switch active workflow. Usage: !set <name>")
    @command.argument("name", required=True)
    async def set_handler(self, evt: MessageEvent, name: str) -> None:
        if not self.workflow_mgr:
            await evt.reply("Workflow manager unavailable.")
            return
        if not name.startswith(API_WORKFLOW_NAME_PREFIX):
            name = API_WORKFLOW_NAME_PREFIX + name
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.workflow_mgr.set_active, name)
            await evt.reply(f"Active workflow: `{name[len(API_WORKFLOW_NAME_PREFIX):]}`")
        except KeyError:
            await evt.reply(f"No workflow named `{name[len(API_WORKFLOW_NAME_PREFIX):]}`.\n{self._list_str()}")

    @command.new("register", help="Save active workflow. Usage: !register <name>")
    @command.argument("name", required=True)
    async def register_handler(self, evt: MessageEvent, name: str) -> None:
        if not self.workflow_mgr:
            await evt.reply("Workflow manager unavailable (pysssss not installed in ComfyUI).")
            return
        if not name.startswith(API_WORKFLOW_NAME_PREFIX):
            name = API_WORKFLOW_NAME_PREFIX + name
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.workflow_mgr.register, name)
            await evt.reply(f"Registered as `{name[len(API_WORKFLOW_NAME_PREFIX):]}`.")
        except Exception as e:
            await evt.reply(f"Registration failed: {e}")

    @command.new("reset", help="Roll back active workflow to baseline")
    async def reset_handler(self, evt: MessageEvent) -> None:
        if not self.workflow_mgr:
            await evt.reply("Workflow manager unavailable.")
            return
        self.workflow_mgr.reset_active()
        await evt.reply("Workflow reset to baseline.")
