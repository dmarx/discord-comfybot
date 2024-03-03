import pytest
from comfy_utils.workflow_manager import Workflow, WorkflowManager

def test_fetch():
    wf = Workflow(name="_api_default")
    assert wf._data == {}
    wf.fetch()
    assert wf._data != {}

def test_lazyload():
    wf = Workflow(name="_api_default")
    assert wf._data == {}
    assert wf.data != {} # lazy loads when this attribute invoked
    assert wf._data != {}
    assert len(wf.data.values())
