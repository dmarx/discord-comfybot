import string
import copy

API_WORKFLOW_NAME_PREFIX = '_api_'

#######################################

def set_node_by_title(workflow, target_node, target_attr, value):
    workflow = copy.deepcopy(workflow)
    for node_id, node in workflow.items():
        if node['_meta']['title'] == target_node:
            node['inputs'][target_attr] = value
    return workflow


def is_valid_api_workflow(w):
    # lol i wish
    # could probably at least check for absence of a key or that all values are conformant nodes
    return True

########################################

def sanitize_title(title):
    title= title.strip()
    for g in string.punctuation:
        if g in ('_','-'):
            continue
        title = title.replace(g, ' ')
    title = title.title() 
    title = title.replace(' ','')
    return title

def prep_workflow(workflow):
    """
    * sanitize titles so they conform to the titling requirements for parameter setting
    """
    # track node titles we've seen to enforce uniqueness
    titles = set()
    w = workflow
    for v in w.values():
        curr_title = v['_meta']['title']
        curr_title = sanitize_title(curr_title)
        while curr_title in titles:
            curr_title += '-'
        titles.add(curr_title)
        v['_meta']['title'] = curr_title

    for v in w.values():
        curr_title = v['_meta']['title']
        n = 0
        while curr_title.endswith('-'):
            curr_title = curr_title[:-1]
            n+=1
        if n:
            curr_title += str(n+1)
        v['_meta']['title'] = curr_title
    return workflow


def summarize_workflow(workflow):
    outstr=''
    for v in workflow.values():
        recs = []
        for p, q in v['inputs'].items():
            if type(q)==list:
                continue
            recs.append((p,q))
        n = len(recs)
        if not n:
            continue
        outstr += f"{v['class_type']} - '{v['_meta']['title']}'\n"
        for k,v in recs:
            n-=1
            pad = "├──" if n>0 else "└──"
            outstr += f"  {pad} {k}: {v}\n"
        outstr+="\n"
    return outstr