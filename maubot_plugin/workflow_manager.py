"""
Adapted from comfy_utils — imports changed to local (.) so this module is
self-contained inside the Maubot plugin package.
"""
import json
import os
from collections import UserDict
from copy import deepcopy
from typing import Dict, Optional

from loguru import logger

from .comfy_client import fetch_saved_workflow, list_saved_workflows, save_workflow
from .workflow_utils import (
    API_WORKFLOW_NAME_PREFIX as api_prefix,
    is_valid_api_workflow,
    summarize_workflow,
)


class Workflow(UserDict):
    def __init__(self, name: str, data: dict = None):
        self.name = name
        self._data = data or {}
        self._baseline = deepcopy(self._data)
        self._uncommitted_changes = False

    @property
    def data(self):
        if not self._data:
            self.fetch()
        return self._data

    def reset(self):
        self._data = deepcopy(self._baseline)
        self._uncommitted_changes = False

    def commit(self):
        response = save_workflow(self.name, self.data)
        self._baseline = deepcopy(self.data)
        self._uncommitted_changes = False

    def summarize(self):
        return summarize_workflow(self.data)

    def fetch(self):
        data = fetch_saved_workflow(self.name)
        if is_valid_api_workflow(data):
            self._data = data
            if not self._baseline:
                self._baseline = deepcopy(self._data)

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
    Interface for managing workflows stored in ComfyUI via the pysssss custom node.
    Workflow listing/saving requires pysssss to be installed in ComfyUI.
    Core generation (get_outputs) works without it.
    """

    def __init__(
        self,
        workflow_registry: Dict[str, Optional[Workflow]] = None,
        default_workflow_name: str = f"{api_prefix}default",
        active_workflow_name=None,
    ):
        self.workflow_registry = workflow_registry or {}
        self.default_workflow_name = default_workflow_name
        self.set_active(active_workflow_name)

    @property
    def active_workflow(self):
        return self.workflow_registry[self._active_workflow_name]

    def refresh_workflow_registry(self):
        self.workflow_registry = {
            wf_name: Workflow(name=wf_name)
            for wf_name in list_saved_workflows(api_only=True)
        }

    def reset(self, all=False):
        if all:
            for wf in self.workflow_registry.values():
                wf.reset()
        else:
            self.active_workflow.reset()

    def register(self, name=None, workflow: Optional[Workflow] = None):
        if not workflow:
            workflow = deepcopy(self.active_workflow)
        if name:
            workflow.name = name
        workflow.commit()
        self.workflow_registry[workflow.name] = workflow

    def set_active(self, wf_name):
        if wf_name is None:
            wf_name = os.environ.get('COMFYCLI_ACTIVE_WORKFLOW', self.default_workflow_name)
        if wf_name not in self.workflow_registry:
            self.refresh_workflow_registry()
            if wf_name not in self.workflow_registry:
                raise KeyError(f"No workflow named {wf_name!r}")
        self._active_workflow_name = wf_name

    def commit(self):
        self.active_workflow.commit()
