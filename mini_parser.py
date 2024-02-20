"""
Parser for a simple argument specification grammar

    PROMPT --NodeName1.attributeName attribute value --NodeName2.attributeName ...
"""

import json
import rich
from loguru import logger


# There should probably be a way for the user to specify this.
# Would need to include resetting the map with the default workflow in .reset
def load_args_map(fpath="special_args_map.json"):
    logger.info('loading args map')
    with open(fpath) as f:
        return json.load(f)

special_args_map = load_args_map()

def parse_arg_name(argname):
    if '.' not in argname:
        return special_args_map.get(argname, False)
    node_name, attribute_name = argname.split('.')
    return {'node_name':node_name, 'target_attr':attribute_name}


def parse_args(in_str: str)->dict:
    args = {}
    splitted = in_str.split(sep='--', maxsplit=1)
    if len(splitted) > 1:
        prompt, args_str = splitted
        args_str = f"--{args_str}"
    else:
        prompt, args_str = splitted, None
    if isinstance(prompt, list):
        prompt = prompt[0]
    args['prompt'] = prompt

    if args_str:
        chunks = args_str.split('--')
        for chunk in chunks:
            if not chunk.strip(): # first entry may be empty
                continue
            if ' ' not in chunk:
                args[chunk] = True
                continue
            k,v = chunk.split(sep=' ', maxsplit=1)
            v = v.strip()
            if v == '':
                v=True
            args[k] = v
    
    node_args = {}
    other_args = {}
    for k,v in args.items():
        rec = parse_arg_name(k)
        if rec:
            rec['value'] = v
            node_args[k] = rec
        else:
            other_args[k] = v
    return {'node_args':node_args, 'other_args':other_args}

if __name__ == '__main__':
    test = "this is my prompt --arg1 --arg2 --karg k arg value --karg2 val2 --arg3 --SomeNode.some_attr val --AnotherNode.some_attr"
    rich.print(parse_args(test))