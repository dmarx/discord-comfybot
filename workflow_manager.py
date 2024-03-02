from collections import UserDict #, UserString
from copy import deepcopy
#from dataclasses import dataclass
from typing import Dict #, List, Union, Optional


import json

from comfy_client import (
    # get_images,
    # server_address,
    # client_id,
    # comfy_is_ready,
    # list_available_checkpoints,
    # list_available_loras,
    # #restart_comfy,
    # get_model_zoo,
    # #################
    fetch_saved_workflow,
    list_saved_workflows,
    fetch_saved_workflow,
    save_workflow,
)
from workflow_utils import (
    is_valid_api_workflow,
    # summarize_workflow,
    # prep_workflow,
    # set_node_by_title,
)


class Workflow(UserDict):
    def __init__(self, name:str, data:dict=None):
        #if not data:
        #    data = fetch_saved_workflow(name)
        if not data:
            data = {}
        #assert is_valid_api_workflow(data)
        self.name = name
        self.data = data
        self._baseline = deepcopy(self.data)
        self._uncommitted_changes = False

    def reset(self):
         self.data = deepcopy(self._baseline)
    
    def commit(self):
        if not self._uncommitted_changes:
            return
        response = save_workflow(self.name, self.data)
        happy_with_status_code = True # todo: check response status code here. 200 or 201 I think?
        if happy_with_status_code:
            self._baseline = deepcopy(self.data)
            self._uncommitted_changes = False
        else:
            # emit some kind of alert to the user. raise an exception or throw a warning.
            pass
    
    def __getitem__(self, k):
        if not self.data:
            # lazy loading
            data = fetch_saved_workflow(self.name)
            if is_valid_api_workflow(data):
                self.data=data
            else:
                # raise custom warning or exception?
                pass
        return self.data[k]

    def __setitem__(self, k, v_new):
        v_current = self.data[k]
        if v_current != v_new:
            self.data[k] = v_new
            self._uncommitted_changes = True

    def __str__(self):
        return json.dumps(self.data)


# todo: instead of metadata on the bot, make a WorkflowManager class and move it to workflow_utils. 
# can then just attach all the relevant functions as methods
class WorkflowManager:
    """
    Interface for managing workflows.
    * local cache of workflow registry
    * local cache of an "active" workflow that can carry modifications relative to its original state
    * utilities for fetching and saving workflows
    """
    def __init__(self,
        workflow_registry: Dict[str, Workflow | None ], # {name, workflow}
        default_workflow_name: str = 'default',
    ):
        if not workflow_registry:
            workflow_registry = {}
        #if not active_workflow:
        #    active_workflow = default_workflow_name
        self.workflow_registry = workflow_registry
        self.default_workflow_name = default_workflow_name
        self.set_active(default_workflow_name)

    @property
    def active_workflow(self):
        return self.workflow_registry[self.active_workflow_name]
    
    def refresh_workflow_registry(self):
        self.data = {wf_name:Workflow(wf_name) for wf_name in list_saved_workflows(api_only=True)}

    def reset(self, all=False):
        """
        Rollback any uncommitted changes on workflows that have them.
        Or should this be limited to the active workflow? we'll let the user pick.
        """
        if all:
            for wf in self.workflow_registry.values():
                wf.reset()
        else:
            self.active_workflow.reset()
        
    def register(self, name=None, workflow:Workflow|None=None):
        """
        Saves the provided workflow to `name`. If no workflow provided, uses the currently active workflow.
        """
        if not workflow:
            workflow = deepcopy(self.active_workflow)
        if name:
            workflow.name = name
        workflow.commit()
        self.workflow_registry[workflow.name] = workflow # code smell: potential for registry name and workflow name to desynch

    def set_active(self, wf_name):
        self._active_workflow_name = wf_name

    def commit(self):
        self.active_workflow.commit()


