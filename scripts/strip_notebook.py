"""Git clean filter: read a notebook on stdin, write it without outputs to stdout.

Configured in .gitattributes (filter=nbstrip), so the committed notebook carries code only
while the working copy keeps its outputs. Outputs here are megabytes of rendered figures
and would also republish whatever a cell happened to print.
"""
import json
import sys


def strip(nb):
    for cell in nb.get('cells', []):
        if cell.get('cell_type') == 'code':
            cell['outputs'] = []
            cell['execution_count'] = None
        cell.get('metadata', {}).pop('execution', None)
    nb.get('metadata', {}).pop('widgets', None)
    return nb


if __name__ == '__main__':
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8', newline='\n')
    nb = strip(json.load(sys.stdin))
    json.dump(nb, sys.stdout, indent=1, ensure_ascii=False)
    sys.stdout.write('\n')
