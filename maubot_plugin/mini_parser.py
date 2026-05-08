"""
Adapted from discord_bot/mini_parser.py — loads special_args_map.json
relative to this file's location so it works inside a Maubot plugin package.
"""
import json
from pathlib import Path

from loguru import logger


def load_args_map(fpath=None):
    if fpath is None:
        fpath = Path(__file__).parent / "special_args_map.json"
    try:
        with open(fpath) as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"special_args_map.json not found at {fpath} — no shorthand args available")
        return {}


special_args_map = load_args_map()


def parse_arg_name(argname):
    if '.' not in argname:
        return special_args_map.get(argname, False)
    node_name, attribute_name = argname.split('.', 1)
    return {'node_name': node_name, 'target_attr': attribute_name}


def parse_args(in_str: str) -> dict:
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
            if not chunk.strip():
                continue
            if ' ' not in chunk:
                args[chunk] = True
                continue
            k, v = chunk.split(sep=' ', maxsplit=1)
            v = v.strip()
            if v == '':
                v = True
            args[k] = v

    node_args = {}
    other_args = {}
    for k, v in args.items():
        rec = parse_arg_name(k)
        if rec:
            rec['value'] = v
            node_args[k] = rec
        else:
            other_args[k] = v
    return {'node_args': node_args, 'other_args': other_args}
