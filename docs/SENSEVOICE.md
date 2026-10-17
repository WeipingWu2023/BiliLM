# SenseVoiceSmall 可选后端

当前状态（v0.1.1）：**已安装并下载，Windows 11 CPU 的 6 秒真实音频推理检查通过**。FunASR 1.4.14、匹配的 PyTorch/torchaudio 2.8.0 CPU，核心 NumPy 固定为同时兼容 Whisper 与 FunASR 的 1.26.4。现有 faster-whisper/small 默认值不变。Linux/GPU 接口相同，但真实推理未验收。短片段可用性不等于准确率评测或长音频验收。

## 为什么这样接入

采用 FunASR 内置 `SenseVoiceSmall`，不执行模型仓库里的 Python 代码。上游支持 Mandarin、Cantonese、English 等语言提示；本项目只传受支持的 `language`、`use_itn=False`、`output_timestamp=False` 与 `batch_size=1`。Whisper 的 beam、initial_prompt、hotwords、VAD 参数不会透传给它，也不进行文本热词替换。topic/glossary 仍保存在原配置中，但不声称它们改善此后端的识别。

依赖固定为 `funasr==1.4.14`。适配器从服务器信任目录读取 `config.yaml`，仅选取内置模型、编码器、分词器与声学前端配置，显式提供 `model_conf` 跳过 FunASR 的 hub 模型解析，关闭版本检查、远程代码及外部 VAD/标点/说话人模型。推理入口即使收到 `allow_model_download=true` 也不下载 SenseVoice；下载是单独管理员操作。

## 时间戳与原稿限制

FFmpeg 生成与 Whisper 一致的 16kHz、单声道 PCM16，保留原文件及独立可播放 WAV。每次最多给模型 30 秒音频，不做降噪、不跳过静音、不重写术语、不去重、不启用 ITN。固定不重叠窗口在切点处可能丢失词语，属于需要人工听音核对的实验限制。

返回的 `start/end` 只表示输入窗口，**不是语音边界、句子对齐或逐词时间戳**。`metrics.timestamp_quality = "input-window-only"`；不能据此声称达到 Whisper 的对齐质量，也不能将窗口边界当作有效逐词时间戳计算误差。FunASR 的可选 CTC 时间戳需要独立校验后再加入，此版本不启用。

展示文本只移除 `<|...|>` 控制标签，不插入情绪表情。每个窗口带原标签的模型全文仍保存于 `metrics.raw_model_outputs[].model_text`，对应 `text/start/end` 一并保留；空输出窗也保留在该记录中。原始音频与后续人工参考不变。处理配置、文件 SHA256、模型版本/权重 hash、运行时版本、设备、耗时、每 100ms 采样的进程 RSS 峰值写入 metrics。RSS 包含 Python/模型开销且不是 GPU 显存；采样可能漏掉短暂峰值。

## 获得明确批准后才执行

本机已获用户批准并执行下载和安装；其他使用者仍需主动准备自己的依赖与权重。先停止服务，以免 Windows 中已加载的 DLL 阻碍安装。推荐 `powershell -NoProfile -ExecutionPolicy Bypass -File .\install-models.ps1 -IncludeSenseVoice`。这个脚本还会准备三个 Whisper 高级候选，不会自动跑评测。手动步骤如下：

Windows PowerShell，项目根目录：

```powershell
# 仅在批准安装后：安装匹配的 CPU wheel；GPU 工作者另选对应 CUDA wheel。
.\.venv\Scripts\python.exe -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple -c backend/requirements.lock.txt -r backend/requirements-sensevoice.txt

# 仅在批准下载这个完整 commit 后执行。
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe -m app.sensevoice --download --revision 3847d57b6bdf2dd8875cb1508d2af43d80a16bf7
```

模型缓存默认 `data/models/sensevoice-small`，只下载 `config.yaml`、`configuration.json`、`model.pt`、`chn_jpn_yue_eng_ko_spectok.bpe.model`、`am.mvn` 五个文件。下载先写固定 revision 的 staging 目录，中断可重试；文件完整并写入 `bililm-snapshot.json` 后才原子切换为正式快照。已有非空正式目录仍拒绝覆盖，避免运行中的快照被替换；管理员可设置 `BILILM_SENSEVOICE_MODEL_DIR` 指向新的可信离线目录。HTTP 请求没有任意模型目录参数。手工放入的模型若没有 commit 元数据，只记录文件 hash，不伪称已知仓库版本。

待批准快照：[3847d57b6bdf2dd8875cb1508d2af43d80a16bf7](https://huggingface.co/FunAudioLLM/SenseVoiceSmall/commit/3847d57b6bdf2dd8875cb1508d2af43d80a16bf7)。[官方文件列表](https://huggingface.co/FunAudioLLM/SenseVoiceSmall/tree/3847d57b6bdf2dd8875cb1508d2af43d80a16bf7)标示权重约 936 MB；另需 PyTorch 等运行时，未实测安装后磁盘与内存占用。

配置示例（同一 API/worker）：

```json
{"backend":"sensevoice","model":"SenseVoiceSmall","device":"cpu","language":"yue","allow_model_download":false}
```

真正比较前需要：人工核对的普通话/粤语/中英混合参考；同一音频 hash；固定归一化；独立进程统计两个模型；明确报告窗级时间戳限制。现阶段没有可支持“哪个模型更准”的实测结果。

## 上游依据

- [SenseVoice 官方使用说明](https://github.com/FunAudioLLM/SenseVoice#usage)：语言提示、ITN、短音频及长音频切分。
- [FunASR 1.4.14 AutoModel 源码](https://github.com/modelscope/FunASR/blob/v1.4.14/funasr/auto/auto_model.py)：提供 model_conf 后绕过 hub 解析，disable_update 与内置推理路径。
- [FunASR 1.4.14 SenseVoice 源码](https://github.com/modelscope/FunASR/blob/v1.4.14/funasr/models/sense_voice/model.py)：CTC 解码及可选对齐实现。
- [官方模型卡及文件](https://huggingface.co/FunAudioLLM/SenseVoiceSmall)：模型文件及许可证条款应以批准下载时的具体版本为准。
