# OBS 实时中文字幕

实时捕获系统音频 → 语音识别 → 中文翻译 → OBS 字幕显示。
专为 **Windows + NVIDIA GPU** 优化。

当前版本包含：
- 共享处理引擎（CLI / OBS 脚本共用同一套音频→VAD→ASR→翻译逻辑）
- 显式运行状态与错误上报（`starting` / `running` / `stopping` / `stopped` / `failed`）
- 固定模型 revision，支持离线缓存与可审计的启动路径
- `pytest` / `ruff` / GitHub Actions CI 基础质量保障

## 依赖

- Windows 10/11
- NVIDIA GPU + CUDA 12.x
- OBS Studio 28+ (内置 WebSocket v5)
- Python 3.11+

## 安装

```bash
set BUILD_CUDA_EXT=0 && python -m pip install -r requirements.txt
```

说明：
- `requirements.txt` 已锁定为当前最新且相互兼容的一组版本。
- `BUILD_CUDA_EXT=0` 用于避免 `auto-gptq` 在 Windows 上强制编译 CUDA 扩展导致安装失败。

开发工具（可选）：

```bash
python -m pip install -e .[dev]
```

## 两种运行模式

### 模式 A：独立运行（推荐调试用）

通过 OBS WebSocket 推送字幕，需先在 OBS 中启用 WebSocket。

```bash
python main.py
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--asr-model` | `Qwen/Qwen3-ASR-0.6B` | ASR 模型名称 |
| `--asr-language` | 自动检测 | 源语言（如 `en` / `ja` / `zh`） |
| `--target-lang` | `zh` | 目标语言 |
| `--model-cache-dir` | `(空)` | Hugging Face 模型缓存目录 |
| `--offline` | off | 仅从本地缓存加载模型 |
| `--no-remote-model-code` | off | 禁止翻译模型执行远程代码 |
| `--obs-source` | `subtitle` | OBS 文本源名称 |
| `--obs-password` | (空) | WebSocket 密码 |
| `-v` | off | 调试日志 |

### 模式 B：OBS 插件（推荐生产用）

直接在 OBS 内运行，无需 WebSocket，延迟更低。

1. OBS → **工具** → **脚本**
2. Python 设置 → 配置 Python 安装路径
3. 点击 **+** → 选择 `obs_script.py`
4. 配置参数（模型、语言、文本源名称、缓存目录、离线模式）
5. 点击 **▶ 启动**

### 模式 C：本地调试面板

浏览器仪表盘通过 WebSocket 连接 `/ws`，前后端共用 `subtitle_runtime` 的 session core，适合在本地联调运行状态、日志和字幕结果。

```bash
python web_server.py --port 8080
```

启动后访问 `http://localhost:8080`，页面会加载 `web/index.html` 并通过共享运行时会话控制启动 / 停止流程。

## OBS 设置

1. **创建文本源**：场景 → 来源 → **+** → 文本 (GDI+)，命名为 `subtitle`
2. **模式 A 额外步骤**：工具 → WebSocket 服务器设置 → 勾选启用

## 架构

共享运行时逻辑已经收敛到 `subtitle_runtime/` 包，入口层只负责组装适配器：

```
subtitle_runtime/
|- domain/        # RuntimeState / RuntimeStatus / SubtitleEvent
|- application/   # session, speech_pipeline, audio_ingress, ports
|- adapters/      # audio / vad / asr / translator / OBS sinks
`- entrypoints/   # cli.py, obs_plugin.py

main.py           # CLI 入口，走 WebSocket 推送字幕到 OBS
obs_script.py     # OBS 脚本入口，直接通过 obspython 更新文本源
pipeline.py       # 兼容旧调用路径的轻量包装
engine.py         # 兼容旧运行时状态导入路径
```

数据流仍然保持不变：

```
系统音频 -> WASAPI Loopback -> Silero VAD -> Qwen3-ASR-0.6B -> HY-MT1.5 翻译 -> OBS 字幕
```

两种运行模式现在共用同一个后台处理引擎：
- `engine.py` 负责模型初始化、背压控制、健康状态与结果回调
- `pipeline.py` 仅负责 CLI 生命周期与 OBS WebSocket 输出
- `obs_script.py` 仅负责 OBS UI、主线程定时器与文本源更新

## 可复现 / 离线模型准备

固定 revision 定义在 `config.py` 中：
- ASR: `Qwen/Qwen3-ASR-0.6B @ 5eb144179a02acc5e5ba31e748d22b0cf3e303b0`
- Translation: `tencent/HY-MT1.5-1.8B-GPTQ-Int4 @ 614b90aaac3987fbe4d6b3c976000b8c996cf5ca`
- VAD: `snakers4/silero-vad @ fcf78bc84d2eabe64dd38a49c18ef2c55a18e84f`

首次联网预热缓存：

```bash
set HF_CACHE=%CD%\models\hf
set TORCH_HOME=%CD%\models\torch
python -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen3-ASR-0.6B', revision='5eb144179a02acc5e5ba31e748d22b0cf3e303b0', cache_dir=r'%HF_CACHE%'); snapshot_download('tencent/HY-MT1.5-1.8B-GPTQ-Int4', revision='614b90aaac3987fbe4d6b3c976000b8c996cf5ca', cache_dir=r'%HF_CACHE%')"
python -c "import torch; torch.hub.load('snakers4/silero-vad:fcf78bc84d2eabe64dd38a49c18ef2c55a18e84f', 'silero_vad', trust_repo='check')"
```

离线运行：

```bash
set TORCH_HOME=%CD%\models\torch
python main.py --model-cache-dir models\hf --offline
```

说明：
- 默认仍允许翻译模型执行远程代码，以兼容当前 GPTQ 模型加载方式。
- 如果你已经审计并固定了本地模型快照，可加 `--no-remote-model-code` 进一步收紧信任边界。

## 质量检查

```bash
python -m ruff check .
python -m pytest
```
