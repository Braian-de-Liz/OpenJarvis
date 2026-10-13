import os
os.environ['OPENJARVIS_CONFIG'] = 'configs/openjarvis/examples/jarvis-windows.toml'

import openjarvis.tools

from openjarvis.tools.windows_control.system_controls import VolumeControlTool

tool = VolumeControlTool()

# Manually trace through execute logic
params = {'action': 'get'}
action = params.get('action', '')
print('action:', repr(action))
print('action == "get":', action == 'get')

# The exact comparison in the code
if action == 'get':
    print('Branch: get')
elif action == 'set':
    print('Branch: set')
else:
    print('Branch: unknown - falling through to else')

# Now test the execute method
result = tool.execute(**params)
print('Result:', result.content)
print('Success:', result.success)