"""Prints the strings of a binary that match a regular expression. Used to look for engine features.

    python tools/exe_strings.py <file> <regex>
"""
import re
import sys

data = open(sys.argv[1], "rb").read()
pattern = re.compile(sys.argv[2], re.IGNORECASE)
found = set()
for match in re.finditer(rb"[\x20-\x7e]{5,200}", data):
    text = match.group().decode("ascii")
    if pattern.search(text):
        found.add(text)
# UTF-16 strings, as used by the Windows API
for match in re.finditer(rb"(?:[\x20-\x7e]\x00){5,200}", data):
    text = match.group().decode("utf-16-le")
    if pattern.search(text):
        found.add(text)
for text in sorted(found):
    print(text)
