# Phase 2：真实 ASR 比较与人工真值

本轮复用 `app.evaluation` 的 CER、英文 WER、术语及时间候选诊断，不更换默认模型，不重建 ASR 架构。人工真值、音频 hash、模型输出与实验配置是报告的输入。没有人工验证数据时，所有语言层与模型都显示“未测”。

## 首批 9 个槽位

普通话、粤语、中英混合各 3 段，每段约 1–3 分钟。槽位是待准备任务，不能称为已经采集的音频。界面只从用户获授权的 BiliLM 来源或本地文件裁切，保存音频 SHA256、来源、范围和机器草稿；用户反复重听后保存独立参考文本、语言、类别和术语，明确标记人工核对。保留重复、口头词和粤语表达，不把粤语改写为普通话。

建议第二人独立复核；当前初版的人为确认是流程记录，不能技术上保证逐字正确。机器草稿可辅助定位，不能直接变成人工真值；参考文本、音频或术语变化后应重新核对。人工注释记录 `cantonese_error`、`missing_speech`、`hallucinated_speech`、`terminology` 或 `uncertain`，并尽量注明模型。未注明模型的注释不计入某个模型的错误数。

导出的 manifest 沿用既有字段：`id`、`stratum`、`audio`、`audio_sha256`、`reference`、`reference_segments`、`terms`、`human_verified`、`reviewer`；另保留 `revision`、`category` 和 `annotations`。路径相对 manifest 目录解析。评分拒绝未审核、没有 reviewer、空参考、未知语言层、音频缺失或 SHA256 不符的记录。

## 默认只生成报告

在项目根目录、已配置的 Python 环境中运行：

```powershell
.\.venv\Scripts\python.exe scripts/benchmark.py benchmarks/manifest.pending.json --output data/phase2-benchmark.json --markdown docs/PHASE2-BENCHMARK-RESULTS.md
```

没有 `--run` 时只验证清单、导入已有预测并评分；不导入 ASR 引擎、不下载、不推理。JSON 同时保留未归一化参考文本、每个模型原始 segments、完整配置、执行 metrics、模型版本和权重 hash。中文 Markdown 自动列出三种语言、每个实验、未配对和失败预测、错误摘录、人工注释及限制。

已有预测的格式仍是 `clip id -> object/array`：

```json
{
  "mandarin-01": [{
    "source_audio_sha256": "与已审核音频一致的 SHA256",
    "segments": [{"start": 0, "end": 1.5, "text": "原始识别文本"}],
    "config": {"backend": "faster-whisper", "model": "small", "device": "cpu", "beam_size": 5},
    "metrics": {"resolved_model_revision": "实际版本", "weights_sha256": "实际权重 hash"},
    "provenance": "raw-asr"
  }]
}
```

该片段只说明字段格式，不是实测预测。缺少时长或 RSS 时显示“未测”，不填零。平台字幕、原始 ASR 与文字校对分别设置 provenance。配置按完整请求配置及实际解码、预处理、量化、设备、权重和运行时版本生成实验身份；beam、提示、硬件或模型版本不同不会混成一行。相同配置同一片段出现重复预测时拒绝汇总，需显式添加 trial 配置或单独出报告。配对覆盖按实际共同 clip id 列出；未配对样本不能用于模型优劣判断。

## 获批准后才执行的比较

当前不运行以下命令。先完成人工真值、批准可选依赖与模型下载，再批准 CPU/GPU 实验任务：

```powershell
.\.venv\Scripts\python.exe scripts/benchmark.py data/groundtruth/manifest.json --run --models small SenseVoiceSmall --device cpu --output data/phase2-benchmark.json --markdown docs/PHASE2-BENCHMARK-RESULTS.md
```

默认 `require_cached_model=True`，Whisper 先查本地缓存、子进程设置 `HF_HUB_OFFLINE=1`；SenseVoice 仅使用独立安装的完整本地快照。不会下载模型，不会失败后自动换引擎。`--allow-model-download` 是 Whisper 的额外显式授权选项；SenseVoice 的下载仍通过独立维护命令及固定 commit 完成。

每个片段每个模型用独立子进程，避免另一个已加载模型污染 RSS。记录后端加载/预处理/转录耗时、含进程启动的总耗时及 100ms 采样 RSS；RSS 含 Python/运行时并可能漏过瞬时峰值，不能冒充精确 OS 高水位或 GPU 显存。不同模型按相同 source SHA256 读取音频，后端各自保留实际预处理配置；首轮是后端基线比较，不声称隔离了单一模型因素。

`--beam 5/8`、`--language auto/zh/yue/en`、`--no-glossary`、`--no-vad` 用于后续单因素对照；SenseVoice 的实际能力、忽略参数和切窗策略由其 metrics 明示，不把 Whisper 参数假装成已应用。两后端模型版本使用各自 revision；需要固定 revision 时分别运行并合并预测，不能给不同仓库硬套同一 commit。

## 指标与证据边界

- CER 使用既有 NFKC、小写、去空格标点规则，保留简繁差异；微平均为总距离除以总参考字符。
- WER 仅对英文/数字 token 报告；不对没有人工分词的中文猜 WER。
- 术语按人工参考中的实际出现次数计算召回、精确、遗漏及多余出现；提示词本身不计作识别正确。
- 粤语特有表达、真实省略、幻觉由人工听音注释；字符增删、重复、重叠、静音窗内输出只是候选诊断。
- SenseVoiceSmall 当前最多 30 秒固定输入窗边界，不是逐词或语音边界。其时间 MAE、缺段覆盖、静音内语音候选不计分，明确显示未测；原始带控制标签输出保存在 metrics。切窗可能截断词语，是应单独实验的限制。
- 只有相同音频、人工参考、明确配置及足够语言覆盖才能讨论准确率；9 段初始样本不足以代表所有教育视频，不给默认模型排名、泛化百分比或显著性结论。

下一步是完成 9 段音频与逐字核对，先比较 small 与 SenseVoiceSmall 的真实错误和成本，再决定是否开展切窗/语言/术语消融。medium、large-v3、GPU/Linux 验证留待额外批准。
