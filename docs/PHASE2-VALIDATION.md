# Phase 2 实施与验证记录

日期：2026-10-15（Asia/Shanghai）。本轮复用现有 backend、SQLite、ASRBackend、evaluation 和 benchmark CLI；未另建队列或分布式基础设施。

## 已落地

- 真值工作区：右上角“真值标注”，普通话、粤语、中英混合各 3 个空槽位。
- 授权本地文件或已有保留音轨裁切，60–180 秒；原媒体与旧裁切文件保留；来源、范围、预处理和 SHA256 记录。
- 机器稿单独展示且只供参考。人工参考原文独立保存，支持区间重复播放、分类、术语和疑难标记。复制机器文字仍是未核对草稿。
- 逐句听音/实际语言确认、核对人、独立确认动作；不确定标注阻止确认为真值。修改使核对失效，修订历史只追加，音频变更拒绝验证/导出。
- 可选 SenseVoiceSmall 适配器与质量菜单，默认仍 faster-whisper/small。推理仅加载本地模型快照，没有网页下载入口；忽略的不支持参数明确说明。
- 原评测框架扩展：相同音频 hash、配置分组、配对片段、原文/版本保留、CER、英文 token WER、术语、候选缺段/重复/静音输出、人工粤语/幻觉注释、耗时/RSS 及中文报告。
- 初音插画 v2 为完整透明剪影；移除首页色块卡片，使用 contain 防止人物再次裁切；旧素材保留。

## 实际检查

`python -m unittest discover -s backend/tests -v`：**58 项通过**。包括此前原稿/版本、任务租约/恢复、缓存与 API 测试，新增真值与报告安全测试、可选后端模拟测试、cached-only 禁止 small 自动下载。真实 FFmpeg/ffprobe 将临时 61 秒静音夹具裁切为 60 秒，HTTP Range 返回 206 并可读 WAV；该夹具不标为人工真值，也不参与识别准确率比较。

`npm run build`：生产构建与 TypeScript 检查通过。浏览器使用本机 Headless Edge，1440×1000 与 390×844：

- `scripts/ui-check.cjs`：现有资料库、文稿标签、搜索、编辑保存后还原、助手原文引用与跳转、SRT 下载，深浅色及手机布局通过。
- `scripts/ground-truth-ui-check.cjs`：9 槽位、初始参考为空、禁止未核对导出、核对动作禁用、粤语分类、未保存离开保护、SenseVoice 参数禁用、透明插画与无横向溢出通过。没有 API 写请求，没有创建真实参考。
- 插画浏览器像素检查：容器透明，object-fit=contain，图像四边非透明像素为 0，人物没有触及画布边缘。截图位于 `docs/screenshots/phase2-home-*` 与 `ground-truth-*`。

## 尚未执行与证据边界

真实样本为 **0**、人工逐字真值为 **0**、本轮实际模型比较为 **0**。`benchmarks/manifest.pending.json` 只记录 9 个空槽位；dry CLI 结果为 verified=0、scored=0、inference_started=false。中文报告所有指标为“未测”，不提供模型准确率排名。

未安装 SenseVoice 运行依赖、未下载模型、未运行真实 SenseVoice 推理或耗时/内存比较。模拟适配器测试只验证参数与数据路径，不能证明 Windows CPU 实际模型推理已经验收。当前最多 30 秒输入窗时间不是语音对齐；固定切窗可能影响边界词，需要正式实验。没有进行 Linux/GPU、云部署或大模型长任务。

下一步：先获批安装可选依赖与固定版本约 936 MB 模型文件，再验证短音频推理；人工完成 9 段真值之后，另行获批执行同音频 small / SenseVoiceSmall 对照。每一语言层分别看 CER、术语和人工确认错误，结合耗时与 RSS 决定下一次实验；本轮不更改默认模型。
