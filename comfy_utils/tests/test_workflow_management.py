import copy
import pytest

from comfy_utils.workflow_manager import Workflow, WorkflowManager

from comfy_utils.workflow_utils import (
    #summarize_workflow,
    #prep_workflow,
    set_node_by_title,
)


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


###################################################################
# modifying the workflow through bracket notation on the object   # 
# (or via the .data attribute..?) should trigger change detection #
###################################################################

def test_change_detection__class_setter():
    wf = Workflow(name="_api_default")
    wf.fetch()
    d0 = copy.deepcopy(wf._data)
    assert d0 == wf._baseline
    assert not wf._uncommitted_changes

    wf['3'] = "foo"
    assert wf._uncommitted_changes

    d1 = copy.deepcopy(wf._data)
    assert d0 == wf._baseline
    assert d0 != d1

def test_snbt_change_detection():
    wf = Workflow(name="_api_default")
    wf.fetch()
    rec = {'node_name':'Ksampler', 'target_attr':'seed', 'value': 42}
    assert not wf._uncommitted_changes
    wf = set_node_by_title(wf, rec['node_name'], rec['target_attr'], rec['value'])
    assert wf._uncommitted_changes



# # this test fails
# def test_change_detection__property_setter():
#     wf = Workflow(name="_api_default")
#     wf.fetch()
#     d0 = copy.deepcopy(wf._data)
#     assert d0 == wf._baseline
#     assert not wf._uncommitted_changes

#     wf.data['3'] = "foo"
#     assert wf._uncommitted_changes
