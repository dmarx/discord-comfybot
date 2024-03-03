import copy
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


#################################################################
# modifying the workflow through bracket notation on the object # 
# or via the .data attribute should trigger change detection    #
#################################################################

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


# this test fails
def test_change_detection__property_setter():
    wf = Workflow(name="_api_default")
    wf.fetch()
    d0 = copy.deepcopy(wf._data)
    assert d0 == wf._baseline
    assert not wf._uncommitted_changes

    wf.data['3'] = "foo"
    assert wf._uncommitted_changes