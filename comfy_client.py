
# modified from https://github.com/comfyanonymous/ComfyUI/blob/master/script_examples/websockets_api_example.py
from dotenv import load_dotenv
import json
from loguru import logger
import os
import requests
import urllib.request
import urllib.parse
from urllib.parse import quote
import uuid
import websocket


from workflow_utils import (
    #summarize_workflow,
    #is_valid_api_workflow,
    API_WORKFLOW_NAME_PREFIX,
)


load_dotenv()

server_address = os.environ.get('COMFY_URL', 'localhost:8188')
client_id = str(uuid.uuid4())

###################################################################

def get_object_info():
    response = requests.get(f"http://{server_address}/object_info")
    return response.json()

def list_available_checkpoints():
    info = get_object_info()
    return info['CheckpointLoaderSimple']['input']['required']['ckpt_name']

def list_available_loras():
    info = get_object_info()
    return info['LoraLoader']['input']['required']['lora_name']

def restart_comfy():
    requests.get(f"http://{server_address}/manager/reboot")

# untested
#def install_missing_custom_nodes():
#    requests.get(f"http://{server_address}/component/get_unresolved")

###################################################################

def get_model_zoo():
    response = requests.get(f"http://{server_address}/externalmodel/getlist?mode=cache")
    return response.json()

#############################################################

#API_WORKFLOW_NAME_PREFIX = '_api_'

def list_saved_workflows(api_only=False):
    response = requests.get(f"http://{server_address}/pysssss/workflows")
    outv = response.json()
    #logger.info(outv)
    outv.sort()
    if api_only:
        prefix = API_WORKFLOW_NAME_PREFIX
        #outv = [w[len(prefix):] for w in outv if w.startswith(prefix)]
        outv = [w for w in outv if w.startswith(prefix)]
    #logger.info(outv)
    return outv

# hmm... i don't think these are in API format :(
def fetch_saved_workflow(name):
    response = requests.get(f"http://{server_address}/pysssss/workflows/{quote(name)}")
    outv = response.json()
    #logger.info(outv)
    return outv




def save_workflow(name, workflow):
    # if api_only:
    #     assert is_valid_api_workflow(workflow)
    #     prefix = API_WORKFLOW_NAME_PREFIX
    #     if not name.startswith(prefix):
    #         name = prefix + name

    payload = {'name':name, 'workflow':workflow}
    payload = json.dumps(payload)
    logger.info(payload)
    response = requests.post(f"http://{server_address}/pysssss/workflows", data=payload)
    return response



# sample payload: {"base":"SDXL","description":"(SDXL Verison) To view the preview in high quality while running samples in ComfyUI, you will need this model.","filename":"taesdxl_encoder.pth","name":"TAESDXL Encoder","reference":"https://github.com/madebyollin/taesd","save_path":"vae_approx","type":"TAESD","url":"https://github.com/madebyollin/taesd/raw/main/taesdxl_encoder.pth","installed":"False"}
# sample zoo entry: {'base': 'efficient_sam', 'description': 'Install efficient_sam_s_gpu.jit into ComfyUI-YoloWorld-EfficientSAM', 'filename': 'efficient_sam_s_gpu.jit', 'name': 'efficient_sam_s_gpu.jit [ComfyUI-YoloWorld-EfficientSAM]', 'reference': 'https://huggingface.co/camenduru/YoloWorld-EfficientSAM/tree/main', 'save_path': 'custom_nodes/ComfyUI-YoloWorld-EfficientSAM', 'type': 'efficient_sam', 'url': 'https://huggingface.co/camenduru/YoloWorld-EfficientSAM/resolve/main/efficient_sam_s_gpu.jit', 'installed': 'False'}
def install_model(name):
    zoo = get_model_zoo()
    payload = None
    for rec in zoo['models']:
        if rec['name'] == name:
            payload = rec
            break
    if payload:
        response = requests.post(f"http://{server_address}/model/install", data=payload)

###################################################################

# consider incorporating tenacity here
def comfy_is_ready() -> bool:
    logger.info(f"Checking if ComfyUI is ready at {server_address}")
    response = requests.get(f"http://{server_address}/queue")
    return response.status_code == 200

def queue_prompt(prompt):
    p = {"prompt": prompt, "client_id": client_id}
    data = json.dumps(p).encode('utf-8')
    req =  urllib.request.Request("http://{}/prompt".format(server_address), data=data)
    return json.loads(urllib.request.urlopen(req).read())

def get_image(filename, subfolder, folder_type):
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    with urllib.request.urlopen("http://{}/view?{}".format(server_address, url_values)) as response:
        return response.read()

def get_history(prompt_id):
    with urllib.request.urlopen("http://{}/history/{}".format(server_address, prompt_id)) as response:
        return json.loads(response.read())

def get_images(ws: websocket.WebSocket, prompt: dict):
    prompt_id = queue_prompt(prompt)['prompt_id']
    output_images = {}
    while True:
        out = ws.recv()
        if isinstance(out, str):
            message = json.loads(out)
            if message['type'] == 'executing':
                data = message['data']
                if data['node'] is None and data['prompt_id'] == prompt_id:
                    break #Execution is done
        else:
            continue #previews are binary data

    history = get_history(prompt_id)[prompt_id]
    for o in history['outputs']:
        for node_id in history['outputs']:
            node_output = history['outputs'][node_id]
            if 'images' in node_output:
                images_output = []
                for image in node_output['images']:
                    image_data = get_image(image['filename'], image['subfolder'], image['type'])
                    images_output.append(image_data)
            output_images[node_id] = images_output

    return output_images
