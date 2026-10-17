"""Read-only hardware/RSS diagnostics; unknown is never reported as zero memory."""
import ctypes
import os
import shutil
import subprocess


def memory():
    if os.name == 'nt':
        class Status(ctypes.Structure):
            _fields_ = [('length',ctypes.c_ulong),('load',ctypes.c_ulong)] + [(n,ctypes.c_ulonglong) for n in ('total','available','page_total','page_available','virtual_total','virtual_available','extended')]
        status = Status(); status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.total / 2**30, status.available / 2**30
    else:
        try:
            from pathlib import Path
            fields={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:','MemAvailable:'))}
            return fields['MemTotal']/2**30,fields['MemAvailable']/2**30
        except (OSError,KeyError,ValueError):
            pass
    return None, None


def rss_bytes():
    if os.name == 'nt':
        class Counters(ctypes.Structure):
            _fields_ = [('cb',ctypes.c_ulong),('faults',ctypes.c_ulong)] + [(n,ctypes.c_size_t) for n in ('peak','working','quota_peak_paged','quota_paged','quota_peak_nonpaged','quota_nonpaged','pagefile','peak_pagefile')]
        counters = Counters(); counters.cb = ctypes.sizeof(counters)
        ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p,ctypes.c_void_p,ctypes.c_ulong]
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(handle,ctypes.byref(counters),counters.cb):
            return counters.working
    else:
        try:
            from pathlib import Path
            return int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
        except (OSError,ValueError,IndexError):
            pass
    return None


def detect():
    total, available = memory()
    gpu, vram = [], None
    path = shutil.which('nvidia-smi')
    if path:
        try:
            result = subprocess.run([path,'--query-gpu=name,memory.total,memory.free','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=5,check=True)
            for line in result.stdout.splitlines():
                name, capacity, free = line.rsplit(',',2)
                gpu.append({'name':name.strip(),'vram_gib':float(capacity)/1024,'free_vram_gib':float(free)/1024})
            if gpu:
                vram = gpu[0]['free_vram_gib']
        except (ValueError,OSError,subprocess.SubprocessError):
            pass
    try:
        import ctranslate2
        cuda = ctranslate2.get_cuda_device_count()
    except Exception:
        cuda = 0
    return {'cpu_threads':os.cpu_count(),'ram_gib':total,'available_ram_gib':available,'cuda_devices':cuda,'gpus':gpu,'available_vram_gib':vram}


def warnings(model, device, hardware):
    messages = []
    estimated = {'tiny':1,'base':1,'small':2,'medium':5,'large-v3':8,'turbo':4,'SenseVoiceSmall':4}.get(model,4)
    actual = 'cuda' if device == 'auto' and hardware['cuda_devices'] else ('cpu' if device == 'auto' else device)
    if actual == 'cpu' and model in ('medium','large-v3','turbo'):
        messages.append('当前使用 CPU，大模型可能显著慢于视频时长；速度必须实测。')
    available = hardware['available_ram_gib'] if actual == 'cpu' else hardware['available_vram_gib']
    if available is None:
        messages.append('无法确认可用内存/显存，请监控资源使用。')
    elif available < estimated:
        messages.append(f'可用内存/显存约 {available:.1f} GiB，低于此模型粗略预算 {estimated} GiB；可能加载失败。这不是实测模型内存。')
    if model=='SenseVoiceSmall':
        messages.append('SenseVoice 为可选实验后端；实际设备由 PyTorch 检测，需另行安装运行依赖和已批准的本地模型。未完成真值对照。')
    if actual == 'cuda' and not hardware['cuda_devices'] and model!='SenseVoiceSmall':
        messages.append('CTranslate2 未检测到 CUDA；选择 GPU 会失败，请使用 CPU/自动。')
    return messages
