import json
with open('config.json', encoding='utf-8') as f:
    c = json.load(f)
with open('tmp_config.txt', 'w', encoding='utf-8') as f:
    json.dump(c.get('executor_overrides'), f, ensure_ascii=False, indent=2)
