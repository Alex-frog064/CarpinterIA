import importlib
mods = [
    'services.order_extraction',
    'tools.order_tools',
    'tools.carpentry_tools',
    'database.db',
    'services.order_agent'
]
for m in mods:
    try:
        importlib.reload(importlib.import_module(m))
        print('OK', m)
    except Exception as e:
        print('ERR', m, e)
