# OBS 实时中文字幕

实时捕获系统音频 → 语音识别 → 中文翻译 → OBS 字幕显示。
专为 **Windows + NVIDIA GPU** 优化。

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
| `--obs-source` | `subtitle` | OBS 文本源名称 |
| `--obs-password` | (空) | WebSocket 密码 |
| `-v` | off | 调试日志 |

### 模式 B：OBS 插件（推荐生产用）

直接在 OBS 内运行，无需 WebSocket，延迟更低。

1. OBS → **工具** → **脚本**
2. Python 设置 → 配置 Python 安装路径
3. 点击 **+** → 选择 `obs_script.py`
4. 配置参数（模型、语言、文本源名称）
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
