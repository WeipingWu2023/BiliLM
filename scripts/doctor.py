import ctypes
import os
import platform
import shutil
import subprocess

print('OS:',platform.platform())
print('Python:',platform.python_version())
print('Logical CPUs:',os.cpu_count())
if os.name == 'nt':
    class Memory(ctypes.Structure):
        _fields_ = [('length',ctypes.c_ulong),('load',ctypes.c_ulong)] + [(n,ctypes.c_ulonglong) for n in ['total','available','page_total','page_available','virtual_total','virtual_available','extended']]
    memory = Memory(); memory.length = ctypes.sizeof(memory)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        print('RAM GiB:',round(memory.total/2**30,1),'available:',round(memory.available/2**30,1))
for tool in ('node','npm','ffmpeg','nvidia-smi'):
    path = shutil.which(tool)
    print(tool+':',path or 'not found')
    if tool == 'nvidia-smi' and path:
        subprocess.run([path,'--query-gpu=name,memory.total','--format=csv'],timeout=10)
print('Default ASR: CPU int8; small. Use tiny/base on low-memory devices.')
