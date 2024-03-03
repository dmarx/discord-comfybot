from collections import UserDict
from copy import deepcopy
import os
from typing import Dict


import json

from .comfy_client import (
    fetch_saved_workflow,
    list_saved_workflows,
    fetch_saved_workflow,
    save_workflow,
)
from .workflow_utils import (
    #API_WORKFLOW_NAME_PREFIX,
    is_valid_api_workflow,
    summarize_workflow,
    # prep_workflow,
    # set_node_by_title,
)
from .workflow_utils import API_WORKFLOW_NAME_PREFIX as api_prefix

from loguru import logger

class Workflow(UserDict):
    def __init__(self, name:str, data:dict=None):
        if not data:
            data = {}
        #assert is_valid_api_workflow(data)
        self.name = name
        self._data = data
        self._baseline = deepcopy(self._data)
        self._uncommitted_changes = False
        self._default_wf_name = f"{api_prefix}default" # fallback source for _baseline ... ami even using this?
    
    @property
    def data(self):
        if not self._data:
            self.fetch()
        return self._data
    
    @data.setter
    def data(self, other):
        if isinstance(other, Workflow):
            self._data = deepcopy(other.data)
        elif isinstance(other, str):
            self._data = deepcopy(Workflow(name=other).data)
        elif isinstance(other, dict):
            self._data = deepcopy(other)
        else:
            raise NotImplementedError
        
        self._uncommitted_changes = True

    def reset(self):
         self._data = deepcopy(self._baseline)
         self._uncommitted_changes = False
    
    def commit(self):
        #if not self._uncommitted_changes:
        #    return
        response = save_workflow(self.name, self.data)
        happy_with_status_code = True # todo: check response status code here. 200 or 201 I think?
        if happy_with_status_code:
            self._baseline = deepcopy(self.data)
            self._uncommitted_changes = False
        else:
            # emit some kind of alert to the user. raise an exception or throw a warning.
            pass
    
    def summarize(self):
        return summarize_workflow(self.data)
    
    def fetch(self):
        # populates lazy loading
        data = fetch_saved_workflow(self.name)
        if is_valid_api_workflow(data):
            self._data=data
            if not self._baseline:
                self._baseline = deepcopy(self._data)
        else:
            # raise custom warning or exception?
            pass
    
    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v_new):
        v_current = self.data[k]
        if v_current != v_new:
            self.data[k] = v_new
            self._uncommitted_changes = True

    def __str__(self):
        return json.dumps(self.data)


class WorkflowManager:
    """
    Interface for managing workflows.
    * local cache of workflow registry
    * local cache of an "active" workflow that can carry modifications relative to its original state
    * utilities for fetching and saving workflows
    """
    def __init__(self,
        workflow_registry: Dict[str, Workflow | None ] = None, # {name, workflow}
        default_workflow_name: str = f"{api_prefix}default",
        active_workflow_name=None,
    ):
        if not workflow_registry:
            workflow_registry = {}
        self.workflow_registry = workflow_registry
        self.default_workflow_name = default_workflow_name
        self.set_active(active_workflow_name)

    @property
    def active_workflow(self):
        return self.workflow_registry[self._active_workflow_name]
    
    def refresh_workflow_registry(self):
        #self.data = {wf_name:Workflow(wf_name) for wf_name in list_saved_workflows(api_only=True)}
        self.workflow_registry = {wf_name:Workflow(wf_name) for wf_name in list_saved_workflows(api_only=True)}

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
        if wf_name is None:
            wf_name = os.environ.get('COMFYCLI_ACTIVE_WORKFLOW', self.default_workflow_name)
        if wf_name not in self.workflow_registry:
            self.refresh_workflow_registry()
            if wf_name not in self.workflow_registry:
                raise KeyError(f"Unable to locate a workflow named {wf_name}")
        self._active_workflow_name = wf_name
        os.environ['COMFYCLI_ACTIVE_WORKFLOW'] = wf_name

    def commit(self):
        self.active_workflow.commit()
