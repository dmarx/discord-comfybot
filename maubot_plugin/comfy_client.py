"""
Adapted from comfy_utils — relative import of API_WORKFLOW_NAME_PREFIX
changed to local import so this module is self-contained inside the plugin.
"""
import json
import os
import urllib.parse
import urllib.request
import uuid
from urllib.parse import quote

import requests
import websocket
from loguru import logger

from .workflow_utils import API_WORKFLOW_NAME_PREFIX


server_address = os.environ.get('COMFY_URL', 'localhost:8188')
client_id = str(uuid.uuid4())


def get_object_info():
    response = requests.get(f"http://{server_address}/object_info")
    return response.json()


def list_available_checkpoints():
    info = get_object_info()
    return info['CheckpointLoaderSimple']['input']['required']['ckpt_name']


def list_available_loras():
    info = get_object_info()
    return info['LoraLoader']['input']['required']['lora_name']


def get_model_zoo():
    response = requests.get(f"http://{server_address}/externalmodel/getlist?mode=cache")
    return response.json()


def list_saved_workflows(api_only=False):
    """Requires the pysssss custom node in ComfyUI."""
    response = requests.get(f"http://{server_address}/pysssss/workflows")
    outv = response.json()
    outv.sort()
    if api_only:
        outv = [w for w in outv if w.startswith(API_WORKFLOW_NAME_PREFIX)]
    return outv


def fetch_saved_workflow(name):
    """Requires the pysssss custom node in ComfyUI."""
    response = requests.get(f"http://{server_address}/pysssss/workflows/{quote(name)}")
    return response.json()


def save_workflow(name, workflow):
    """Requires the pysssss custom node in ComfyUI."""
    payload = json.dumps({'name': name, 'workflow': workflow})
    response = requests.post(f"http://{server_address}/pysssss/workflows", data=payload)
    return response


def comfy_is_ready() -> bool:
    try:
        response = requests.get(f"http://{server_address}/queue", timeout=5)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def queue_prompt(prompt):
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req = urllib.request.Request(f"http://{server_address}/prompt", data=data)
    return json.loads(urllib.request.urlopen(req).read())


def get_output(filename, subfolder, folder_type):
    params = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": folder_type})
    with urllib.request.urlopen(f"http://{server_address}/view?{params}") as response:
        return response.read()


def get_history(prompt_id):
    with urllib.request.urlopen(f"http://{server_address}/history/{prompt_id}") as response:
        return json.loads(response.read())


def get_outputs(ws: websocket.WebSocket, prompt: dict) -> dict:
    prompt_id = queue_prompt(prompt)['prompt_id']
    while True:
        out = ws.recv()
        if isinstance(out, str):
            message = json.loads(out)
            if message['type'] == 'executing':
                data = message['data']
                if data['node'] is None and data['prompt_id'] == prompt_id:
                    break

    history = get_history(prompt_id)[prompt_id]
    all_outputs = {}
    for node_id in history['outputs']:
        node_output = history['outputs'][node_id]
        for out_type in ('gifs', 'images'):
            if out_type in node_output:
                items = []
                for output in node_output[out_type]:
                    items.append(get_output(output['filename'], output['subfolder'], output['type']))
                if items:
                    all_outputs.setdefault(out_type, []).extend(items)

    return all_outputs
