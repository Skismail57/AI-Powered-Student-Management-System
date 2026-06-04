import re
from collections import Counter

path = 'frontend/admin.html'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

ids = re.findall(r'id="([^"]+)"', content)
duplicates = [item for item, count in Counter(ids).items() if count > 1]

if duplicates:
    print('Duplicate IDs found:')
    for d in duplicates:
        print(f'  - {d}')
        # Find lines
        with open(path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                if f'id="{d}"' in line:
                    print(f'    Line {i+1}: {line.strip()}')
else:
    print('No duplicate IDs found.')
