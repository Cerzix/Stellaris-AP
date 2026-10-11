"""A small reader for Paradox script files.

A block is a list of entries. An entry is (key, operator, value) for "key = value", where the value
is a string or a block, or (value, None, None) for a bare value as in "category = { particles }".
"""
import re
from pathlib import Path

TOKEN = re.compile(r'\s+|#[^\n]*|("(?:[^"\\]|\\.)*")|([{}])|([<>]=?|=)|([^\s{}=<>#"]+)')

Block = list


def positioned_tokens(text: str, start: int = 0, end: int | None = None):
    """Yields (token, position in the text), without whitespace and comments."""
    position = start
    end = len(text) if end is None else end
    while position < end:
        match = TOKEN.match(text, position, end)
        if not match:
            raise ValueError(f"cannot read script at {text[position:position + 30]!r}")
        position = match.end()
        if match.lastindex:
            yield match.group(match.lastindex), match.start(match.lastindex)


def tokens(text: str):
    for token, _ in positioned_tokens(text):
        yield token


def block_spans(text: str, start: int = 0, end: int | None = None) -> list[tuple[str, int, int]]:
    """(key, position of {, position of }) of every "key = { ... }" directly inside text[start:end]."""
    spans = []
    depth = 0
    before = [None, None]  # the two tokens in front of the current one
    opened = None
    for token, position in positioned_tokens(text, start, end):
        if token == "{":
            if depth == 0 and before[1] == "=":
                opened = (before[0], position)
            depth += 1
        elif token == "}":
            depth -= 1
            if depth == 0 and opened:
                spans.append((*opened, position))
                opened = None
        if depth == 0:
            before = [before[1], token]
    return spans


def parse(text: str) -> Block:
    stream = list(tokens(text.lstrip("﻿")))
    block, position = parse_block(stream, 0)
    if position != len(stream):
        raise ValueError("unexpected }")
    return block


def parse_block(stream: list[str], position: int) -> tuple[Block, int]:
    block = []
    while position < len(stream) and stream[position] != "}":
        key = stream[position]
        position += 1
        if key == "{":
            # A block without a key, as in a list of blocks
            value, position = parse_block(stream, position)
            block.append((None, "=", value))
            position += 1
            continue
        if position < len(stream) and stream[position] in ("=", "<", ">", "<=", ">="):
            operator = stream[position]
            value = stream[position + 1]
            position += 2
            if value == "{":
                value, position = parse_block(stream, position)
                if position >= len(stream):
                    raise ValueError(f"missing }} after {key}")
                position += 1
            block.append((key, operator, value))
        else:
            block.append((key, None, None))
    return block, position


def parse_file(path: Path) -> Block:
    return parse(path.read_text(encoding="utf-8-sig", errors="replace"))


def get(block: Block, key: str, default=None):
    """The value of the last entry with this key."""
    for entry_key, _, value in reversed(block):
        if entry_key == key:
            return value
    return default


def values(block: Block) -> list[str]:
    """The bare values of a block, without quotes."""
    return [key.strip('"') for key, operator, _ in block if operator is None]
