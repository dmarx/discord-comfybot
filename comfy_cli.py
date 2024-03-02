from pathlib import Path
from comfy_client import (
    #summarize_saved_workflow,
    list_available_checkpoints,
    list_available_loras,
    list_saved_workflows,
    comfy_is_ready,
    restart_comfy,
    #_save_workflow
)

from workflow_utils import API_WORKFLOW_NAME_PREFIX, is_valid_api_workflow
from workflow_manager import Workflow, WorkflowManager


def summarize_saved_workflow(name):
    # summarize_workflow() assumes api-only
    prefix = API_WORKFLOW_NAME_PREFIX
    if not name.startswith(prefix):
        name = prefix + name

    #w = fetch_saved_workflow(name)
    #assert is_valid_api_workflow(w)
    #outstr = summarize_workflow(w)
    return '\n' + Workflow(name).summarize()


def _save_workflow(name, workflow=None, api_only=True):
    prefix = ''
    if api_only:
        assert is_valid_api_workflow(workflow)
        prefix = API_WORKFLOW_NAME_PREFIX
    if not name.startswith(prefix):
        name = prefix + name
    if workflow is None:
        workflow = f"{name}.json"
    
    assert Path(workflow).exists
    with Path(workflow).open() as f:
       w_data = json.load(f)
    print(w_data)
    wf = Workflow(name, w_data)
    wf.commit()
    #logger.info(name)
    #response = save_workflow(name, w_data)
    #logger.info(response) # 500
    #logger.info(response.text)



if __name__ == '__main__':
    import fire

    cli = {
        'describe': summarize_saved_workflow,
        'list':{
            'models': list_available_checkpoints,
            'loras': list_available_loras,
            'workflows': list_saved_workflows,
            },
        'ready': comfy_is_ready,
        'restart': restart_comfy,
        'save': _save_workflow,
    }

    fire.Fire(cli)
    
    