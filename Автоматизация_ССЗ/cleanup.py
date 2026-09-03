import os
import re

with open('ssz_worker.py', encoding='utf-8') as f:
    c = f.read()

c = re.sub(r"        open\('test_gui_crash\.log'.*?\n", "", c)
c = re.sub(r"open\('test_gui_crash\.log'.*?; ", "", c)

with open('ssz_worker.py', 'w', encoding='utf-8') as f:
    f.write(c)
