import string


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
        #outstr += f"{v['class_type']} - '{v['_meta']['title']}'\n"
        #n = len()
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