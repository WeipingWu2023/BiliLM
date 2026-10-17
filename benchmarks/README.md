# 人工真值与可复现 benchmark

提取获授权的真实短片：`python scripts/prepare_benchmark.py "音频.wav" --stratum mandarin --id mandarin-01 --start 0 --duration 15`。工具只裁切音频并生成带 SHA256 的未审核 manifest，不生成或伪造 reference；同名片段拒绝覆盖。粤语与混合样本分别用 cantonese / zh-en-mixed，并由人工确认实际说话语言，不能用“双语字幕”代替混合语音。

当前用户没有已验证真值，`manifest.pending.json` 是待采集/待核对清单，**不是已完成数据集**。普通话、粤语、中英混合分别报告，不能用一个总数掩盖弱项。先用获授权的真实教育视频，每层收集短片（建议 10–30 秒），涵盖数字、术语、停顿、背景音乐、口音，避免只挑容易片段。

人工流程：两人独立听音逐字记录（保留重复、口头词和中英切换），复核分歧；填写 reviewer、日期、来源许可、reference、精确 reference_segments 与已核实静音区。保留方言本来表达，不把粤语改写成普通话。音频 SHA256 固定；词表包含参考中真实说到的词及负对照，禁止从 ASR 抄答案。无真实样本时不使用合成语音代替实测准确率。

```
python scripts/benchmark.py benchmarks/manifest.pending.json
# 只验证清单，无下载/推理，未审核条目被拒绝。
python scripts/benchmark.py benchmarks/manifest.verified.json --predictions data/predictions.json
# 明确授权才执行大模型推理；默认只用缓存模型，不自动下载。
python scripts/benchmark.py benchmarks/manifest.verified.json --run --models small medium large-v3 turbo --device cuda
# --allow-model-download 是额外、显式的下载授权，仍需用户批准后才执行。
```

每次单独固定 beam=5 或 8；分别执行 auto/zh、multilingual、无词表/词表、VAD开/关对照，不能同时变多个因素后归因。CPU/GPU 与模型分别记录。复现还需要固定代码/运行时版本、模型 commit/权重 hash、FFmpeg、音频 hash 和完整 decoding；相同模型不同量化独立计入实验。微平均 CER 用总编辑距离/总参考字符；不平均不同长度片段的百分比。

CER：NFKC、小写、忽略空格标点；保留简繁差异，不能任意归一为正确。WER 只对真实英文词序列报告；未经人工中文分词，不虚构中文 WER。术语按出现次数匹配并报告遗漏和额外出现。缺片段按 reference 时间覆盖检查；重复、重叠、静音内输出只是候选诊断，真实省略/幻觉仍需人工听音。时间误差按重叠参考窗边界评估，不同切段的影响须阅读原数据。

任意引擎（SenseVoiceSmall、平台字幕、raw ASR、文字校对）都能以统一 predictions JSON 进入 scorer，每项必须带 source_audio_sha256、segments、config、metrics、provenance。校对单独分组，不能混成 raw ASR 改善。导入 SenseVoice 前需完成标记清理及时间对齐，不把整段粗粒度时长冒充逐词时间戳。

自动脚本不推荐默认模型。只有人工验证的数据覆盖三种语言层、错误与成本都审查后才提出默认建议。
