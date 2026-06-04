# MusicGen 配乐服务部署指南

## 快速开始

### 1. 启动（依赖自动安装）

```bash
# large 模型 + 4-bit 量化（推荐，~4GB 显存，效果最好）
python scripts/musicgen_server.py --model large --quantize --port 8000

# medium 模型（~8GB 显存）
python scripts/musicgen_server.py --model medium --port 8000

# small 模型（~4GB 显存，速度快）
python scripts/musicgen_server.py --model small --port 8000
```

首次运行自动检测并安装缺失依赖（`torch`、`transformers`、`soundfile` 等）。
`--quantize` 模式会额外安装 `bitsandbytes` 和 `accelerate`。

首次启动会自动下载模型（~1.5GB / 3.3GB / 6.6GB），之后缓存复用。

### 2. 验证服务

```bash
# 健康检查
curl http://localhost:8000/health

# 测试生成
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "sad piano, gentle", "duration": 10}' \
  -o test.wav
```

### 3. 配置项目

编辑 `config/system.yaml`：

```yaml
music_backend: musicgen
music:
  api_url: "http://GPU机器IP:8000/generate"
  api_key: ""  # 自部署无需填
```

## GPU 显存需求

| 模型 | 参数量 | 显存 (FP16) | 显存 (4-bit) | 生成 30s 耗时 | 效果 |
|------|--------|-------------|-------------|--------------|------|
| small | 300M | ~4GB | — | ~5s | 一般 |
| medium | 1.5B | ~8GB | — | ~15s | 推荐入门 |
| large | 3.3B | ~10GB | **~4GB** | ~30s | 最好 |

**推荐 large + `--quantize`**（4-bit NF4 量化，显存从 ~10GB 降到 ~4GB，T4/15GB 卡均可跑）。

```bash
# 15GB 显存卡 → large + 4-bit 量化（推荐）
python scripts/musicgen_server.py --model large --quantize --port 8000

# T4 (16GB) → medium 或 large + 量化
python scripts/musicgen_server.py --model medium --port 8000
```

## 国内平台部署

### AutoDL

1. 租实例（推荐 3090，¥2.1/小时）
2. 选择 PyTorch 2.0 + CUDA 12 镜像
3. SSH 进入，执行「快速开始」
4. 使用「自定义服务」功能暴露 8000 端口
5. 拿到公网地址配到项目 `music.api_url`

### 矩池云

同上，选 GPU 实例 → 装依赖 → 启动 → 拿地址。

### 阿里云 PAI-EAS

可以做成常驻服务，按 GPU 时长计费。适合生产环境。

## API 文档

### POST /generate

生成配乐，返回 WAV 音频。

**请求:**
```json
{
  "prompt": "sad piano, gentle, emotional background music",
  "duration": 30
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| prompt | string | ✅ | 音乐描述（英文效果最好） |
| duration | int | ❌ | 时长秒数，5-120，默认 30 |

**响应:** `audio/wav` 二进制

### GET /health

健康检查。

**响应:**
```json
{
  "status": "ok",
  "model": "musicgen-medium",
  "device": "cuda:0",
  "samplerate": 32000
}
```

> **注意**: 若遇到 `AuxRequest` 导入错误，锁定 transformers：`pip install transformers==4.57.6`（5.x 早期版本有此 bug，4.45+ 已修复）

## mood → prompt 映射

项目会根据镜头情绪自动选择 prompt：

| mood | prompt |
|------|--------|
| happy | happy upbeat cheerful background music, light and joyful |
| sad | sad melancholic piano, gentle and emotional background music |
| angry | intense dramatic aggressive background music, powerful and dark |
| romantic | romantic gentle love theme, soft piano and strings |
| calm | calm peaceful serene ambient music, relaxing and tranquil |
| action | action energetic fast-paced background music, exciting and dynamic |

也可以在镜头中直接指定 `prompt` 字段覆盖 mood 映射。

## 环境踩坑记录

### 版本锁定（脚本自动处理，此表仅供参考）

> 脚本首次运行会自动安装以下依赖，无需手动操作。

| 包 | 推荐版本 | 说明 |
|---|---|---|
| `transformers` | `>=4.45,<5.0` | 4.45+ 修复了 `AuxRequest` 导入 bug |
| `numpy` | `>=1.24,<2.0` | 1.x 兼容 soundfile/librosa，2.x 二进制接口不兼容 |
| `torch` | `>=2.10.0` | 需支持 CUDA 12.x |

快速安装：
```bash
pip install "transformers>=4.45,<5.0" "numpy>=1.24,<2.0"
```

### libcusparseLt.so.0 找不到

**症状**：`ImportError: libcusparseLt.so.0: cannot open shared object file`

**根因**：PyTorch 2.10+ 编译时链接了 CUDA 12.6 的 `libcusparseLt`（稀疏矩阵加速库），系统 CUDA（如 12.2）只有 `libcusparse` 没有 `libcusparseLt`。nvidia pip 包 `nvidia-cusparselt` 提供了这个库，但不在系统默认搜索路径中。

**排查**：
```bash
# 确认库文件存在（在 pip 安装的 nvidia 包中）
find / -name "libcusparseLt*" 2>/dev/null
# 通常在: ~/.pyenv/versions/3.11.1/lib/python3.11/site-packages/nvidia/cusparselt/lib/
```

**修复**（按部署方式选择）：

```bash
# 方案 A：shell 环境（开发机/裸机部署）
echo 'export LD_LIBRARY_PATH="/path/to/nvidia/cusparselt/lib:$LD_LIBRARY_PATH"' >> ~/.zshrc
source ~/.zshrc

# 方案 B：Docker（Dockerfile 或 docker run --env）
ENV LD_LIBRARY_PATH="/path/to/nvidia/cusparselt/lib:${LD_LIBRARY_PATH}"

# 方案 C：systemd service（ExecStart 前加环境）
Environment="LD_LIBRARY_PATH=/path/to/nvidia/cusparselt/lib"

# 方案 D：通用（patchelf 永久写入 Python 二进制，不依赖环境变量）
patchelf --add-rpath /path/to/nvidia/cusparselt/lib $(python -c "import torch; print(torch.__file__)")
```

### nvidia-smi CUDA Version vs nvcc CUDA Version

`nvidia-smi` 显示的是**驱动支持的最高 CUDA 版本**（如 13.0），`nvcc` 显示的是**实际安装的 CUDA Toolkit 版本**（如 12.2）。两者可以不同，PyTorch pip 包自带 CUDA runtime，不依赖系统 CUDA Toolkit。

## 常见问题

**Q: 首次请求很慢？**
A: 首次加载模型到 GPU 需要 30-60s，后续请求秒级。

**Q: 生成的音乐质量不好？**
A: 试试 large 模型（加 `--quantize` 省显存），或用更详细的英文 prompt（加上风格、乐器、节奏等描述）。

**Q: large 模型 OOM？**
A: 加 `--quantize` 参数启用 4-bit NF4 量化，显存从 ~16GB 降到 ~4GB。需要安装 `bitsandbytes` 和 `accelerate`。

**Q: 能生成纯音乐不要人声吗？**
A: prompt 里加 `instrumental, no vocals`。

**Q: 能指定 BPM/节奏吗？**
A: 可以，prompt 里加 `120 bpm` 或 `slow tempo`。
