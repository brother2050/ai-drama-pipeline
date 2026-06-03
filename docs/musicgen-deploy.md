# MusicGen 配乐服务部署指南

## 快速开始

### 1. 环境准备（GPU 机器）

```bash
pip install fastapi uvicorn transformers soundfile torch
```

### 2. 启动服务

```bash
# medium 模型（推荐，5GB 显存，效果好）
python scripts/musicgen_server.py --model medium --port 8000

# small 模型（2GB 显存，速度快）
python scripts/musicgen_server.py --model small --port 8000

# large 模型（8GB 显存，效果最好）
python scripts/musicgen_server.py --model large --port 8000
```

首次启动会自动下载模型（~1.5GB / 3.3GB / 6.6GB），之后缓存复用。

### 3. 验证服务

```bash
# 健康检查
curl http://localhost:8000/health

# 测试生成
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "sad piano, gentle", "duration": 10}' \
  -o test.wav
```

### 4. 配置项目

编辑 `config/system.yaml`：

```yaml
music_backend: musicgen
music:
  api_url: "http://GPU机器IP:8000/generate"
  api_key: ""  # 自部署无需填
```

## GPU 显存需求

| 模型 | 参数量 | 显存 | 生成 30s 耗时 | 效果 |
|------|--------|------|--------------|------|
| small | 300M | ~2GB | ~5s | 一般 |
| medium | 1.5B | ~5GB | ~15s | 推荐 |
| large | 3.3B | ~8GB | ~30s | 最好 |

推荐 **medium + T4/A10/3090**。

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

## 常见问题

**Q: 首次请求很慢？**
A: 首次加载模型到 GPU 需要 30-60s，后续请求秒级。

**Q: 生成的音乐质量不好？**
A: 试试 large 模型，或用更详细的英文 prompt（加上风格、乐器、节奏等描述）。

**Q: 能生成纯音乐不要人声吗？**
A: prompt 里加 `instrumental, no vocals`。

**Q: 能指定 BPM/节奏吗？**
A: 可以，prompt 里加 `120 bpm` 或 `slow tempo`。
