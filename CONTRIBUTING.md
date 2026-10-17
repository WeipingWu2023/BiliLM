# 参与开发

优先修复可复现问题、补充文档和人工评测数据工作流。请保持原始稿不可覆盖，不把 AI 或 OCR 内容标为已听音验证，不在常规测试中下载模型或调用付费 API。

## 手动安装与启动

Windows 使用 Python 3.12 x64、Node 22+ 和 FFmpeg：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --index-url https://pypi.org/simple -r backend/requirements.lock.txt
cd frontend
npm.cmd ci --registry=https://registry.npmjs.org
cd ..
$env:PYTHONPATH = "$PWD\backend"
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

第二个终端设置相同 PYTHONPATH 后运行 `.\.venv\Scripts\python -m app.worker`。第三个终端进入 frontend 运行 `npm.cmd run dev`。所有进程使用同一项目目录与 data，端口只绑定 127.0.0.1。

Linux 开发路径：安装 Python 3.12/venv、Node 22+、FFmpeg，使用 `python3.12 -m venv .venv`，之后对应解释器为 `.venv/bin/python`，设置 `export PYTHONPATH="$PWD/backend"`，分别启动同样的 API/worker/前端命令。Windows 一键脚本不会在 Linux 运行；GPU 驱动与真实模型推理需单独验收。

## 验证

- 后端：`python -m unittest discover -s backend/tests -v`（需要先设置 PYTHONPATH 并使用项目虚拟环境）。测试使用 `data/tests` 下临时数据库；无需模型或 Key，部分测试需真实 FFmpeg/ffprobe。
- 前端：在 frontend 中 `npm run typecheck`、`npm run build`、`npm audit --registry=https://registry.npmjs.org`。先停开发服务器再构建。
- 发布隐私检查：在根目录 `python scripts/check_release.py`；检查 Git 跟踪文件，不读取私有运行目录。
- GitHub Actions 在 Windows/Linux 跑后端和隐私检查，并在 Linux 做干净 npm 安装、类型检查、生产构建、依赖审计。它不测真实平台访问和模型准确率。

`scripts/*-ui-check.cjs` 是开发期浏览器回归脚本：需要自行安装 Playwright 和 Edge，可用 `BILILM_PLAYWRIGHT` 指向模块位置。某些脚本依赖本地既有测试笔记，并非面向全新安装的通用冒烟测试。AI 路径使用浏览器模拟或本地模式，不应意外消耗真实 API 费用。

真实 ASR 验收可使用 `scripts/smoke.py`；它会导入来源、等待识别并检查缓存/导出，因此仅在明确选择授权来源、模型和下载预算后手动运行。客观评测先准备人工真值，见 benchmarks/README.md。

## 提交

说明问题、最终行为和验证结果。对模型、VAD、解码或归一化的修改请保留可复现配置；不要只以模型大小、速度或流行程度判断准确率。对未测项明确写“未测”。

不要提交 data、模型权重、真实音视频、数据库、API Key、机器路径或包含私人资料的截图。新增截图请使用无私人资料的状态或明确标注的合成界面示例。第三方素材需要清楚来源与使用边界。
