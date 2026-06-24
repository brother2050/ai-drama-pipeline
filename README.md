# 🎬 AI 短剧全流程生产管线 v2

> 从剧本到成片，一键搞定 — 纯 Python，跨平台，零 Shell 脚本依赖

---

## ✨ 核心特性

| 特性 | 说明 |
|------|------|
| **纯 Python** | 零 Shell 脚本，Windows/macOS/Linux 通用 |
| **API 优先** | 所有三方工具通过 HTTP API 调用，无需本地 GPU |
| **Celery 异步** | Redis + Celery 任务队列，前端实时进度反馈 |
| **一键启动** | `drama serve` + `drama worker` |
| **注册表驱动** | `models_registry.yaml` 统一管理所有后端元数据，新增后端只改 YAML |
| **DI 容器** | 后端自注册 + 按需创建 + 热重载 + 懒加载 |
| **人性化工作台** | 内联编辑、撤销重做、批量执行、资源预览 |
| **多语言界面** | 中文/English 双语支持 |
| **Seko 策划案** | 集成 seko.sensetime.com 影视策划案生成/修改 |
| **IP-Adapter Plus** | 基于 ip-adapter-plus-face 模型的角色面部一致性（SD1.5/SDXL 后端） |
| **PuLID-Flux** | 基于 PuLID 的 Flux 面部一致性（Flux 后端，推荐） |
| **Flux IP-Adapter FaceID** | Shakker-Labs IP-Adapter FaceID Plus（Flux 身份加固，InsightFace + CLIP 双锚定） |
| **自动节点检测** | 启动时自动查询 ComfyUI /object_info，一致性方案按可用节点动态跳过 |
| **声线库** | 1000 种声线一键选用，搜索/试听/分配到角色 |
| **安全加固** | 输入校验、路径遍历防护、速率限制 |
| **防御式后端** | AIToolkitTrainer / ComfyUI / VideoBase 全部标准化 health_check + shutdown |

---

## 🚀 快速开始

### 1. 克隆

```bash
git clone https://ghfast.top/https://github.com/brother2050/ai-drama-pipeline.git
cd ai-drama-pipeline
```

### 2. 安装依赖

```bash
# 基础安装（Web + Celery + TTS 云 API）
pip install -e .

# 含横转竖人脸追踪
pip install -e ".[vertical]"

# 全量安装
pip install -e ".[all]"
```

<details>
<summary>可选依赖详情</summary>

| 安装方式 | 包 | 用途 | 不装影响 |
|---------|---|------|---------|
| `.[vertical]` | face_recognition | 横转竖人脸追踪定位 | 回退到模糊背景 |
| `.[vertical]` | opencv-python-headless | 视频帧读取 | 回退到模糊背景 |

不装可选包时，各功能自动降级，不会崩溃。

</details>

### 3. 下载基础模型（按选择的后端）

> 项目启动前必须下载至少一个图像后端的基础模型。模型放到 `ComfyUI/models/` 对应子目录。

#### 📌 模型下载总览

| 后端 | UNet / Checkpoint | CLIP | VAE | 显存需求 |
|------|-------------------|------|-----|---------|
| **Cosmos（默认推荐）** | `cosmos_predict2_2B_t2i.safetensors` | `oldt5_xxl_fp8_e4m3fn_scaled.safetensors` | `wan_2.1_vae.safetensors` | ~12GB |
| **Flux** | `flux1-dev.safetensors` | `clip_l.safetensors` + `t5xxl_fp16.safetensors` | Flux 自带 | **≥32GB** |
| **Flux FP8** | `flux1-dev-fp8.safetensors` | `clip_l.safetensors` + `t5xxl_fp8_e4m3fn_scaled.safetensors` | Flux 自带 | ~16GB |
| **SD1.5** | `v1-5-pruned-emaonly.safetensors` | Checkpoint 自带 | Checkpoint 自带 | ~6GB |
| **CogVideoX（可选）** | `cogvideox-5b.safetensors` | `t5xxl_fp16.safetensors` | `cogvideox_vae.safetensors` | ≥24GB |
| **HiDream（可选）** | `hidream_e1_full_bf16.safetensors` | 四重 CLIP（见下文） | `ae.sft` | ≥24GB |

> **GPU 兼容性速查**：
>
> | GPU | 显存 | 推荐后端 | 说明 |
> |-----|------|---------|------|
> | T4 | 16GB | Cosmos / SD1.5 / Flux FP8 | Flux fp16 不行 |
> | A10 | 24GB | Cosmos / SD1.5 / Flux FP8 | Flux fp16 不行 |
> | V100-32G | 32GB | Flux / Flux FP8 / Cosmos | Flux fp16 可用，fp8 更省 |
> | A100-40G | 40GB | Flux fp16 / Cosmos | 全部后端可用 |
> | A100-80G | 80GB | 全部 | 无限制 |

#### 方案 A：Cosmos 后端（推荐，12GB 显存即可）

```bash
# 1. UNet 模型 → ComfyUI/models/diffusion_models/
mkdir -p ComfyUI/models/diffusion_models/
wget -O ComfyUI/models/diffusion_models/cosmos_predict2_2B_t2i.safetensors \
  https://huggingface.co/nvidia/Cosmos-Predict2-2B-Text2Image/resolve/main/cosmos_predict2_2B_t2i.safetensors

# 2. CLIP 模型（T5-XXL FP8）→ ComfyUI/models/clip/
mkdir -p ComfyUI/models/clip/
wget -O ComfyUI/models/clip/oldt5_xxl_fp8_e4m3fn_scaled.safetensors \
  https://huggingface.co/nvidia/Cosmos-Predict2-2B-Text2Image/resolve/main/oldt5_xxl_fp8_e4m3fn_scaled.safetensors

# 3. VAE → ComfyUI/models/vae/
mkdir -p ComfyUI/models/vae/
wget -O ComfyUI/models/vae/wan_2.1_vae.safetensors \
  https://huggingface.co/nvidia/Cosmos-Predict2-2B-Text2Image/resolve/main/wan_2.1_vae.safetensors
```

> **Cosmos 视频生成**（可选，用于 `cosmos-video` 视频后端）：
> ```bash
> wget -O ComfyUI/models/diffusion_models/cosmos_predict2_2B_video2world_480p_16fps.safetensors \
>   https://huggingface.co/nvidia/Cosmos-Predict2-2B-Video2World/resolve/main/cosmos_predict2_2B_video2world_480p_16fps.safetensors
> ```

#### 方案 B：Flux 后端（≥32GB 显存）

```bash
# 1. UNet 模型 → ComfyUI/models/diffusion_models/（或 ComfyUI/models/unet/）
mkdir -p ComfyUI/models/diffusion_models/
wget -O ComfyUI/models/diffusion_models/flux1-dev.safetensors \
  https://huggingface.co/Comfy-Org/flux1-dev/resolve/main/flux1-dev.safetensors

# 2. CLIP 模型 → ComfyUI/models/clip/
mkdir -p ComfyUI/models/clip/
wget -O ComfyUI/models/clip/clip_l.safetensors \
  https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors
wget -O ComfyUI/models/clip/t5xxl_fp16.safetensors \
  https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors

# 3. VAE：Flux UNet 自带 VAE，无需单独下载
```

> **FP8 省显存版**（T4/A10 推荐，显存从 32GB+ 降到 ~16GB，使用 `flux-fp8` 后端）：
> ```bash
> # UNet 用 FP8 替代 FP16，CLIP 也用 FP8 版
> wget -O ComfyUI/models/diffusion_models/flux1-dev-fp8.safetensors \
>   https://huggingface.co/Kijai/flux-fp8/resolve/main/flux1-dev-fp8.safetensors
> wget -O ComfyUI/models/clip/clip_l.safetensors \
>   https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors
> wget -O ComfyUI/models/clip/t5xxl_fp8_e4m3fn_scaled.safetensors \
>   https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn_scaled.safetensors
> ```
> 下载后在 `config/system.yaml` 中设置 `models.image_backend: flux-fp8`。

> **Flux 写实 LoRA**（推荐下载，放入 `ComfyUI/models/loras/`）：
> ```bash
> # flux-RealismLora（超写实人像）
> wget -O ComfyUI/models/loras/flux-realism-lora.safetensors \
>   https://huggingface.co/XLabs-AI/flux-RealismLora/resolve/main/flux-realism-lora.safetensors
> # ACE++ Portrait（零训练角色一致性）
> wget -O ComfyUI/models/loras/comfyui_portrait_lora64.safetensors \
>   https://huggingface.co/ali-vilab/ACE_Plus/resolve/main/portrait/comfyui_portrait_lora64.safetensors
> ```

#### 方案 C：SD1.5 后端（≥6GB 显存，入门级）

```bash
# 1. Checkpoint 模型 → ComfyUI/models/checkpoints/
mkdir -p ComfyUI/models/checkpoints/
wget -O ComfyUI/models/checkpoints/v1-5-pruned-emaonly.safetensors \
  https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.safetensors

# 2. AnimateDiff 运动模块（视频生成必须）→ ComfyUI/models/animatediff/
mkdir -p ComfyUI/models/animatediff/
wget -O ComfyUI/models/animatediff/mm_sd_v15_v2.ckpt \
  https://huggingface.co/guoyww/animatediff/resolve/main/mm_sd_v15_v2.ckpt
```

> SD1.5 的 CLIP 和 VAE 内嵌在 Checkpoint 中，无需单独下载。
> AnimateDiff 运动模块用于视频生成（生产阶段），不装则无法生成镜头视频。

#### 方案 D：CogVideoX 视频后端（可选，≥24GB 显存）

> CogVideoX 是智谱 AI 开源的视频生成模型，效果优于 AnimateDiff，适合高质量镜头视频生成。
> 需要安装 ComfyUI-CogVideoXWrapper 自定义节点：
> ```bash
> cd ComfyUI/custom_nodes/
> git clone https://github.com/kijai/ComfyUI-CogVideoXWrapper.git
> # 重启 ComfyUI
> ```

```bash
# 1. UNet 模型 → ComfyUI/models/diffusion_models/
mkdir -p ComfyUI/models/diffusion_models/
wget -O ComfyUI/models/diffusion_models/cogvideox-5b.safetensors \
  https://huggingface.co/THUDM/CogVideoX-5b/resolve/main/cogvideox-5b.safetensors

# 2. CLIP 模型（T5-XXL）→ ComfyUI/models/clip/
wget -O ComfyUI/models/clip/t5xxl_fp16.safetensors \
  https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors

# 3. VAE → ComfyUI/models/vae/
wget -O ComfyUI/models/vae/cogvideox_vae.safetensors \
  https://huggingface.co/THUDM/CogVideoX-5b/resolve/main/vae/cogvideox_vae.safetensors
```

> 下载后在 `config/system.yaml` 中设置 `models.video_backend: cogvideox`。

#### 方案 E：HiDream 图像后端（可选，≥24GB 显存）

> HiDream 是一个高质量图像生成模型，支持 img2img 模式（基于首帧重绘）。
> 需要安装 ComfyUI-HiDream 自定义节点：
> ```bash
> cd ComfyUI/custom_nodes/
> git clone https://github.com/SHYuanBest/ComfyUI-HiDream.git
> # 重启 ComfyUI
> ```

```bash
# 1. UNet 模型 → ComfyUI/models/diffusion_models/
mkdir -p ComfyUI/models/diffusion_models/
wget -O ComfyUI/models/diffusion_models/hidream_e1_full_bf16.safetensors \
  https://huggingface.co/HiDream-ai/HiDream-E1-Full/resolve/main/hidream_e1_full_bf16.safetensors

# 2. 四重 CLIP 文本编码器 → ComfyUI/models/text_encoders/
mkdir -p ComfyUI/models/text_encoders/
wget -O ComfyUI/models/text_encoders/clip_g_hidream.safetensors \
  https://huggingface.co/HiDream-ai/HiDream-I1-Full/resolve/main/clip_g_hidream.safetensors
wget -O ComfyUI/models/text_encoders/clip_l_hidream.safetensors \
  https://huggingface.co/HiDream-ai/HiDream-I1-Full/resolve/main/clip_l_hidream.safetensors
wget -O ComfyUI/models/text_encoders/t5xxl_fp8_e4m3fn_scaled.safetensors \
  https://huggingface.co/HiDream-ai/HiDream-I1-Full/resolve/main/t5xxl_fp8_e4m3fn_scaled.safetensors
wget -O ComfyUI/models/text_encoders/llama_3.1_8b_instruct_fp8_scaled.safetensors \
  https://huggingface.co/HiDream-ai/HiDream-I1-Full/resolve/main/llama_3.1_8b_instruct_fp8_scaled.safetensors

# 3. VAE（Flux 同款）→ ComfyUI/models/vae/
# 如果已下载 Flux 的 ae.sft 可跳过
```

> 下载后在 `config/system.yaml` 中设置 `models.image_backend: hidream`。

#### 📁 目录结构参考

```
ComfyUI/models/
├── diffusion_models/     # UNet 模型（Flux / Cosmos / CogVideoX / HiDream）
│   ├── flux1-dev.safetensors
│   ├── cosmos_predict2_2B_t2i.safetensors
│   ├── cosmos_predict2_2B_video2world_480p_16fps.safetensors
│   ├── cogvideox-5b.safetensors
│   └── hidream_e1_full_bf16.safetensors
├── checkpoints/          # SD1.5 Checkpoint
│   └── v1-5-pruned-emaonly.safetensors
├── animatediff/          # AnimateDiff 运动模块（SD1.5 视频生成）
│   └── mm_sd_v15_v2.ckpt
├── clip/                 # 文本编码器（Flux / Cosmos / CogVideoX）
│   ├── clip_l.safetensors
│   ├── t5xxl_fp16.safetensors
│   ├── t5xxl_fp8_e4m3fn_scaled.safetensors
│   └── oldt5_xxl_fp8_e4m3fn_scaled.safetensors
├── text_encoders/        # 文本编码器（HiDream 四重 CLIP）
│   ├── clip_g_hidream.safetensors
│   ├── clip_l_hidream.safetensors
│   ├── t5xxl_fp8_e4m3fn_scaled.safetensors
│   └── llama_3.1_8b_instruct_fp8_scaled.safetensors
├── vae/                  # VAE 解码器
│   ├── wan_2.1_vae.safetensors       # Cosmos
│   └── cogvideox_vae.safetensors     # CogVideoX
├── ipadapter/            # IP-Adapter 模型（SD1.5/SDXL，第 6 节）
├── ipadapter-flux/       # Flux IP-Adapter FaceID 模型（第 8.5 节）
├── pulid/                # PuLID-Flux 模型（第 7 节）
├── clip_vision/          # CLIP Vision 编码器
├── insightface/          # InsightFace 人脸模型
└── loras/                # LoRA 模型（训练产出）
```

### 4. 启动 Redis + PostgreSQL（必选）

```bash
# Ubuntu
sudo apt install redis-server && sudo systemctl start redis
sudo apt install postgresql && sudo systemctl start postgresql

# macOS
brew install redis && brew services start redis
brew install postgresql@16 && brew services start postgresql@16

# Docker
docker run -d -p 6379:6379 redis:7-alpine
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=drama123 -e POSTGRES_USER=drama -e POSTGRES_DB=ai_drama postgres:16-alpine
```

#### 初始化数据库（Ubuntu / macOS 手动安装）

安装完成后，创建用户和数据库:

```bash
# 1. 创建 drama 用户（若尚不存在）
sudo -u postgres psql -c "CREATE USER drama WITH PASSWORD 'drama123';"

# 2. 创建 ai_drama 数据库（属主为 drama）
sudo -u postgres psql -c "CREATE DATABASE ai_drama OWNER drama;"

# 3. 授予 drama 用户建表权限
sudo -u postgres psql -c "GRANT ALL ON DATABASE ai_drama TO drama;"
```

> **macOS 注意**：Homebrew 安装后默认用户为系统用户名。若 `sudo -u postgres` 无效，可先用系统用户连接创建：
> ```bash
> psql -h 127.0.0.1 -U $(whoami) -d postgres -c "CREATE USER drama WITH PASSWORD 'drama123' SUPERUSER;"
> psql -h 127.0.0.1 -U $(whoami) -d postgres -c "CREATE DATABASE ai_drama OWNER drama;"
> ```

> **PostgreSQL 启动失败？（macOS 僵尸锁文件）**
>
> 若 `brew services` 显示 `error`，日志提示 `lock file "postmaster.pid" already exists`：
> ```bash
> # 检查是否有残留 postgres 进程
> ps aux | grep postgres | grep -v grep
> # 无运行进程则可安全删除锁文件
> rm /usr/local/var/postgresql@16/postmaster.pid
> # Apple Silicon 路径可能是 /opt/homebrew/var/postgresql@16/postmaster.pid
> # 重启服务
> brew services restart postgresql@16
> ```

### 5. 配置

```bash
cp .env.example .env
# 编辑 .env，必填:
#   AI_DRAMA_DB_DSN=postgresql://drama:drama123@127.0.0.1:5432/ai_drama
#   MIMO_API_KEY=（语音合成免费）
#   SEKO_API_KEY=（影视策划案，可选）
# 获取 MIMO_API_KEY: https://api.xiaomimimo.com
# 获取 SEKO_API_KEY: https://seko.sensetime.com/explore
```

### 6. 启动

> ⚠ **需要打开两个终端窗口**，分别运行 Worker 和 Web 工作台。它们是独立进程，不能在同一终端同时运行。

```bash
# 终端 1: 启动 Celery Worker（处理异步任务）
drama worker

# 终端 2: 启动 Web 工作台
drama serve

# 浏览器打开 http://localhost:8888
```

> **并发数说明**：默认 concurrency=2，个人使用推荐 2-4。
>
> 主生产流程（镜头生产）内部是逐镜头串行执行的，concurrency 设置不影响主流程速度。并发数主要影响 Web 工作台中多个操作同时提交时的响应（如同时生成定妆照和场景图）。外部服务（ComfyUI/TTS）通常是单实例单任务，设置过高的并发不会加速反而浪费内存。
>
> ```bash
> drama worker -c 2   # 默认，省资源
> drama worker -c 4   # Web 操作较多时推荐
> ```

### 7. IP-Adapter Plus（角色面部一致性，可选但强烈推荐）

> 基于 [ComfyUI_IPAdapter_plus](https://github.com/cubiq/ComfyUI_IPAdapter_plus) 实现跨镜头角色面部一致性。安装后定妆照的面部特征会通过 IP-Adapter 注入到每个镜头的首帧生成中，大幅提升同一角色在不同镜头间的辨识度。

#### ⚠️ 后端兼容性

| 图像后端 | 架构 | 可用一致性方案 | 说明 |
|---------|------|:-------------:|------|
| `flux` | DiT | **PuLID-Flux + Flux IP-Adapter FaceID** | **推荐**，双层管道：PuLID 做主锚定 + FaceID IP-Adapter 加固 |
| `sd15` | UNet | IP-Adapter Plus | 成熟稳定，面部一致性好 |
| `cosmos` | DiT | 无 | 仅 LoRA 训练 |

> Flux 后端默认启用 `flux_identity` **一致性管道**：PuLID-Flux（Layer 1）→ Flux IP-Adapter FaceID（Layer 2），两层叠加实现最强的身份保持。若 ComfyUI 缺少 FaceID 插件，自动降级为纯 PuLID。
>
> 一致性方案与后端**独立配置**，通过 `consistency_method` 字段选择：

```yaml
# config/system.yaml
consistency_method: auto   # auto / pulid_flux / ip_adapter / none
#   auto:        根据 image_backend 自动选择（flux→pulid_flux + flux_ip_adapter 管道, sd15→ip_adapter, cosmos→none）
#   pulid_flux:  强制使用 PuLID-Flux（需 Flux 后端）
#   ip_adapter:  强制使用 IP-Adapter Plus（需 SD1.5/SDXL 后端）
#   none:        不使用一致性方案（仅靠 LoRA + seed）
```

> **启动时自动检测**：管线启动时会调用 ComfyUI `/object_info` 端点获取已注册节点类型，与 YAML 中每个一致性方案的 `required_comfyui_nodes` 比对。若所需插件未安装，对应方案自动跳过（带 Warning 日志），不会报错中断。

#### 6.1 安装 ComfyUI 自定义节点

```bash
cd ComfyUI/custom_nodes/
git clone https://github.com/cubiq/ComfyUI_IPAdapter_plus.git
# 重启 ComfyUI
```

#### 6.2 下载模型文件

**方案 A：SD1.5 后端（推荐，IP-Adapter Plus 兼容）**

需要下载 **1 个 IP-Adapter 模型** + **1 个 CLIP Vision 编码器**：

```bash
# 1. IP-Adapter 模型 → 放入 ComfyUI/models/ipadapter/
#    目录不存在则手动创建: mkdir -p ComfyUI/models/ipadapter/
wget -O ComfyUI/models/ipadapter/ip-adapter-plus-face_sd15.safetensors \
  https://huggingface.co/h94/IP-Adapter/resolve/main/models/ip-adapter-plus-face_sd15.safetensors

# 2. CLIP Vision 编码器 → 放入 ComfyUI/models/clip_vision/
wget -O ComfyUI/models/clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors \
  https://huggingface.co/h94/IP-Adapter/resolve/main/models/image_encoder/model.safetensors
```

**方案 B：SDXL 后端**

```bash
# IP-Adapter 模型（SDXL 版）
wget -O ComfyUI/models/ipadapter/ip-adapter-plus-face_sdxl_vit-h.safetensors \
  https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/ip-adapter-plus-face_sdxl_vit-h.safetensors

# CLIP Vision 编码器（SDXL 用 bigG）
wget -O ComfyUI/models/clip_vision/CLIP-ViT-bigG-14-laion2B-39B-b160k.safetensors \
  https://huggingface.co/h94/IP-Adapter/resolve/main/sdxl_models/image_encoder/model.safetensors
```

<details>
<summary>全部可用模型</summary>

**SD1.5 系列**（CLIP Vision: `CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors`）

| 模型 | 说明 |
|------|------|
| `ip-adapter-plus-face_sd15.safetensors` | **默认推荐**，面部一致性最强 |
| `ip-adapter-plus_sd15.safetensors` | 通用 Plus，风格+内容保持 |
| `ip-adapter-full-face_sd15.safetensors` | 更强面部保持，可能过度拟合 |
| `ip-adapter_sd15.safetensors` | 基础模型，影响最弱 |

**SDXL 系列**（CLIP Vision: `CLIP-ViT-bigG-14-laion2B-39B-b160k.safetensors`）

| 模型 | 说明 |
|------|------|
| `ip-adapter-plus-face_sdxl_vit-h.safetensors` | SDXL 面部模型 |
| `ip-adapter-plus_sdxl_vit-h.safetensors` | SDXL 通用 Plus |
| `ip-adapter_sdxl.safetensors` | SDXL 基础（需 bigG 编码器） |

</details>

#### 6.3 配置

IP-Adapter 默认已启用，配置在 `config/system.yaml` 中：

```yaml
ip_adapter:
  enabled: true
  model: "ip-adapter-plus-face_sd15.safetensors"   # SD1.5 面部模型
  clip_vision: "CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors"
  weight: 0.75              # 参考图权重（官方建议 ≤0.8）
  secondary_weight: 0.45    # 多角色时次要角色权重
  embeds_scaling: "V only"  # 面部特征保持最佳的缩放模式
```

> 如使用 SDXL 后端，将 `model` 改为 `ip-adapter-plus-face_sdxl_vit-h.safetensors`，`clip_vision` 改为 `CLIP-ViT-bigG-14-laion2B-39B-b160k.safetensors`。

#### 6.4 验证

启动后在 Web 工作台仪表盘查看 IP-Adapter 状态，或 CLI：

```bash
drama status   # 应显示 IP-Adapter Plus ✅
```

### 8. PuLID-Flux（Flux 面部一致性，推荐）

> 基于 [PuLID](https://github.com/ToTheBeginning/PuLID) 的 Flux 面部一致性方案。通过 InsightFace 检测人脸 + EVA CLIP 编码面部特征，将 ID embedding 注入 Flux DiT 注意力层，实现跨镜头角色面部一致性。

#### 8.1 安装 ComfyUI 自定义节点

```bash
cd ComfyUI/custom_nodes/
git clone https://github.com/balazik/ComfyUI-PuLID-Flux.git
# 可选增强版（更多融合方法）：
# git clone https://github.com/sipie800/ComfyUI-PuLID-Flux-Enhanced.git
# 重启 ComfyUI
```

#### 8.2 下载模型文件

需要下载 **3 类模型**：

```bash
# 1. PuLID Flux 模型 → ComfyUI/models/pulid/
mkdir -p ComfyUI/models/pulid/
wget -O ComfyUI/models/pulid/pulid_flux_v0.9.0.safetensors \
  "https://huggingface.co/guozinan/PuLID/resolve/main/pulid_flux_v0.9.0.safetensors"

# 2. InsightFace AntelopeV2（5 个文件）→ ComfyUI/models/insightface/models/antelopev2/
mkdir -p ComfyUI/models/insightface/models/antelopev2/
wget -O ComfyUI/models/insightface/models/antelopev2/1k3d68.onnx \
  https://hf-mirror.com/MonsterMMORPG/tools/resolve/main/1k3d68.onnx
wget -O ComfyUI/models/insightface/models/antelopev2/2d106det.onnx \
  https://hf-mirror.com/MonsterMMORPG/tools/resolve/main/2d106det.onnx
wget -O ComfyUI/models/insightface/models/antelopev2/genderage.onnx \
  https://hf-mirror.com/MonsterMMORPG/tools/resolve/main/genderage.onnx
wget -O ComfyUI/models/insightface/models/antelopev2/glintr100.onnx \
  https://hf-mirror.com/MonsterMMORPG/tools/resolve/main/glintr100.onnx
wget -O ComfyUI/models/insightface/models/antelopev2/scrfd_10g_bnkps.onnx \
  https://hf-mirror.com/MonsterMMORPG/tools/resolve/main/scrfd_10g_bnkps.onnx

# 3. EVA02-CLIP-L-14-336 → 首次运行自动下载（或手动放到 ComfyUI/models/clip/）
```

#### 8.3 配置

PuLID-Flux 默认已启用，配置在 `config/system.yaml` 中：

```yaml
pulid_flux:
  enabled: true
  model: "pulid_flux_v0.9.0.safetensors"
  weight: 0.9              # 推荐 0.8-0.95（1.0 过拟合）
  fusion: "mean"           # 多图融合方法: mean / concat / max / train_weight
  use_gray: true           # 灰度优化（边缘轮廓更自然）
```

#### 8.4 技巧

- **参考图质量很重要**：使用清晰、正面、光线均匀的定妆照
- **weight 推荐 0.8-0.95**：1.0 容易过拟合，面部僵硬
- **Euler + simple** 调度器始终可用；Euler + beta 对低质量参考图效果更好
- **多角色同框**：自动链式注入，主角色 weight=0.9，次要角色自动降权

#### 8.4 管道联动

Flux 后端默认启用 `flux_identity` 一致性管道，PuLID-Flux 作为 Layer 1（人脸锚定），自动叠加 Layer 2 的 Flux IP-Adapter FaceID 做身份加固。管道各层独立可用性检测，ComfyUI 缺少某层插件时自动降级。

### 8.5 Flux IP-Adapter FaceID（Shakker-Labs，身份加固层）

> 基于 [Shakker-Labs/ComfyUI-IPAdapter-Flux](https://github.com/Shakker-Labs/ComfyUI-IPAdapter-Flux.git) 的 FaceID Plus 版本。通过 InsightFace ArcFace 提取人脸 ID embedding + CLIP-ViT-L 图像嵌入，双重锚定实现跨镜头身份一致。
>
> **在 `flux_identity` 管道中作为 Layer 2 运行**（Layer 1 为 PuLID-Flux），两层的 weight 独立可调。

#### 8.5.1 安装 ComfyUI 自定义节点

```bash
cd ComfyUI/custom_nodes/
git clone https://github.com/Shakker-Labs/ComfyUI-IPAdapter-Flux.git
# 重启 ComfyUI
```

或在 ComfyUI Manager 中搜索 `ComfyUI-IPAdapter-Flux` 安装。

节点类名：`IPAdapterFluxLoader` / `ApplyIPAdapterFlux`

#### 8.5.2 下载模型文件

> 模型来自 [InstantX/FLUX.1-dev-IP-Adapter](https://huggingface.co/InstantX/FLUX.1-dev-IP-Adapter)。
> InsightFace ArcFace 提取人脸 ID embedding + CLIP-ViT-L (SigLIP) 图像嵌入，双重锚定实现跨镜头身份一致。

| 文件名 | 位置 | 说明 |
|--------|------|------|
| `ip-adapter.bin` | `ComfyUI/models/ipadapter-flux/` | IP-Adapter 权重 |
| `siglip-so400m-patch14-384.safetensors` | `ComfyUI/models/clip_vision/` | CLIP Vision 编码器 |

**国内镜像**：
```bash
# ip-adapter.bin
wget -O ComfyUI/models/ipadapter-flux/ip-adapter.bin \
  https://hf-mirror.com/InstantX/FLUX.1-dev-IP-Adapter/resolve/main/ip-adapter.bin

# siglip
wget -O ComfyUI/models/clip_vision/siglip-so400m-patch14-384.safetensors \
  https://hf-mirror.com/google/siglip-so400m-patch14-384/resolve/main/model.safetensors
```

#### 8.5.3 配置

Flux IP-Adapter FaceID 配置在 `config/system.yaml` 中：

```yaml
ip_adapter_flux_shakker:
  enabled: true
  model: "ip-adapter.bin"                            # InstantX IP-Adapter 权重
  weight: 0.7              # 管道 Layer 2 权重（Layer 1 PuLID 为主锚，此层为加固）
```

#### 8.5.4 验证

```bash
drama status   # 检查 IPAdapterFluxLoader / ApplyIPAdapterFlux 节点是否可用
```

#### 8.5.5 管道协同

```
UNETLoader
    │
    ▼ (model)
ApplyPulidFlux          ← Layer 1, PuLID-Flux, weight=0.85（主锚定）
    │
    ▼ (model)
ApplyIPAdapterFlux      ← Layer 2, FaceID IP-Adapter, weight=0.7（加固）
    │
    ▼ (model)
KSampler
```

> 降级行为：若 ComfyUI 缺少 Flux IP-Adapter 节点 → 自动回退为纯 PuLID-Flux（单层）。不会报错中断。

## 8.6 ControlNet Depth（Flux 全身结构一致性，可选）

> 基于 ControlNet Depth 实现全身结构一致性。从角色全身参考图生成 depth map，通过 ControlNet 强制身体结构（体型、姿态、服装轮廓）在不同镜头间保持一致。
> **与 IP-Adapter/PuLID 并行工作**：IP-Adapter/PuLID 负责面部一致性，ControlNet Depth 负责身体结构一致性。

### 8.6.1 安装 ComfyUI 自定义节点

```bash
cd ComfyUI/custom_nodes/

# 1. ControlNet Aux（提供 MiDaS-DepthMapPreprocessor 深度估计节点）
git clone https://github.com/Fannovel16/comfyui_controlnet_aux.git

# 2. XLabs Flux ControlNet（提供 LoadFluxControlNet / ApplyFluxControlNet）
git clone https://github.com/XLabs-AI/x-flux-comfyui.git
```

### 8.6.2 下载模型文件

```bash
# Flux ControlNet Depth V3 模型 → ComfyUI/models/xlabs/controlnets/
# 注意：LoadFluxControlNet（x-flux-comfyui）使用 XLabs 专属目录，非 ComfyUI 标准 controlnet 目录
mkdir -p ComfyUI/models/xlabs/controlnets/
wget -O ComfyUI/models/xlabs/controlnets/flux-depth-controlnet-v3.safetensors \
  "https://hf-mirror.com/XLabs-AI/flux-controlnet-depth-v3/resolve/main/flux-depth-controlnet-v3.safetensors"

# 注：MiDaS 深度估计模型由 comfyui_controlnet_aux 首次运行时自动下载，无需手动操作。
```

> **说明**：
> - MiDaS 深度估计由 `comfyui_controlnet_aux` 插件提供，模型会在首次使用时自动下载。

### 8.6.3 工作流搭建

在 ComfyUI 中搭建如下流程：

```
[角色全身参考图]
       │
       ▼
[MiDaS Depth Preprocessor]  ← 生成 depth map
       │
       ▼
[ApplyFluxControlNet]  ← 加载 flux-controlnet-depth-v3
       │  controlnet_condition
       ▼
[KSampler / XlabsSampler]  ← 与 model / IP-Adapter / PuLID 并行输入
```

**关键节点与参数：**

| 节点 | 说明 |
|------|------|
| **MiDaS-DepthMapPreprocessor** | 输入角色全身参考图，输出 depth map（由 comfyui_controlnet_aux 提供） |
| **LoadFluxControlNet** | 加载 `flux-depth-controlnet-v3.safetensors`，选择 base 为 flux-dev |
| **ApplyFluxControlNet** | strength 建议 0.6–0.8（过高会限制其他条件的灵活性） |

**与 IP-Adapter/PuLID 并行使用的注意事项：**

- ControlNet Depth 控制身体结构，IP-Adapter/PuLID 控制面部——两者不冲突，可同时接入 KSampler。
- 如果同时使用 IP-Adapter，建议 ControlNet Depth strength 设为 **0.5–0.7**，避免两者权重叠加过高导致画面僵硬。
- 全身参考图应选择姿态自然、服装完整的图片，MiDaS 对这类图片的深度估计最准确。

### 8.6.4 配置

ControlNet Depth 默认禁用，配置在 `config/system.yaml` 中：

```yaml
controlnet_depth:
  enabled: true                # 启用 ControlNet Depth
  model: "flux-depth-controlnet-v3.safetensors"
  strength: 0.8                # ControlNet 强度（0.5-1.0，越高结构越严格）
  start_percent: 0.0           # 生效起始步（0.0 = 从头开始）
  end_percent: 1.0             # 生效结束步（1.0 = 全程生效）
```

### 8.6.5 验证

```bash
drama status   # 检查 ControlNet 节点是否可用
```

- 用同一张角色全身参考图生成 3 张不同场景的图片，检查体型、姿态、服装轮廓是否一致。
- 如果身体结构偏移过大，提高 ControlNet strength；如果画面过于僵硬，降低 strength。
- 可同时结合 IP-Adapter 的面部一致性，确认面部和身体均保持一致。

### 8.6.6 说明

- **工作原理**：从角色全身参考图（`full_body.png`）生成 depth map，通过 ControlNet 强制生成图像的深度结构与参考图一致
- **适用场景**：Flux 后端的全身/半身镜头，需要保持角色体型、姿态、服装轮廓一致性
- **与 IP-Adapter 的关系**：两者可以并行使用，IP-Adapter 负责面部特征，ControlNet Depth 负责身体结构
- **显存需求**：额外占用约 2-4GB 显存（MiDaS 深度估计 + ControlNet 模型）

### 9. TTS 后端（语音合成）

> 项目支持 7 种 TTS 后端，按需选择。默认使用小米 MiMo 云 API（免费）。

#### 方案 A：小米 MiMo（默认推荐，零部署）

```bash
# 获取免费 API Key: https://api.xiaomimimo.com
# 在 .env 中设置:
MIMO_API_KEY=your_key_here
```

- **mimo-voicedesign**：预设音色，开箱即用
- **mimo-voiceclone**：声音克隆，上传参考音频即可

#### 方案 B：GPT-SoVITS（语音克隆，音质最好）

> 需要 GPU 服务器。支持 v1（api.py）和 v2（api_v2.py）两套 API，自动探测。

```bash
# 1. 部署 GPT-SoVITS（参考官方文档）
#    https://github.com/RVC-Boss/GPT-SoVITS

# 2. 启动 API 服务
#    v4 模型默认: python api.py -a 0.0.0.0 -p 9880
#    或 v2:       python api_v2.py -a 0.0.0.0 -p 9880

# 3. 配置
# config/system.yaml
models:
  tts_backend: gpt-sovits
  gpt_sovits:
    api_url: http://你的服务器IP:9880
```

**参考音频配置**（每个角色独立）：

```yaml
# projects/<项目>/config/characters/林夏.yaml
character:
  voice:
    # ── 共享参数（跨后端复用）──
    reference_audio: "/path/to/linxia_ref.wav"   # GPT-SoVITS / MiMo-Clone
    voice_description: "清脆甜美的少女音"          # MiMo VoiceDesign
    core_traits: "温柔但坚强"                     # MiMo VoiceDesign
    aux_ref_audio_paths:                          # 辅助参考音频（多说话人音色融合）
      - "/path/to/aux1.wav"

    # ── 后端专属参数 ──
    gpt_sovits:
      prompt_text: "嗯...你好啊"                  # 参考音频的台词
      prompt_lang: "zh"
      speed_factor: 1.0
    chattts:
      voice: "5555"                              # 种子值
    cosyvoice:
      speaker: "default"
```

**远程服务器上传参考音频**：

```bash
# 在 GPT-SoVITS 服务器上运行上传助手
python scripts/gpt_sovits_upload_server.py -p 9881 -d /path/to/refs

# 上传参考音频
curl -X POST "http://服务器IP:9881/upload?name=linxia.wav" --data-binary @ref.wav
```

#### 方案 C：ChatTTS（本地部署，免费）

> Docker 一行命令部署，CPU 也可运行（GPU 更快）。

```bash
# 1. 部署 ChatTTS-ui
docker run -d -p 7860:7860 --restart unless-stopped chattts/chattts-ui:latest

# 2. 配置
# config/system.yaml
models:
  tts_backend: chattts
  chattts:
    api_url: http://127.0.0.1:7860
```

**37 个预设音色**（Web 工作台角色编辑页面下拉选择）：

| 分组 | 种子 | 特征 |
|------|------|------|
| 🧔 低沉男声 | 1031, 13, 5600, 4444, 2279 | 沉稳浑厚 |
| 🧔 温暖男声 | 1983, 4751, 14, 1579, 2222, 99999 | 自然磁性 |
| 🧑 中性声线 | 4785, 492, 16, 7869, 5, 9999, 6653, 4099, 2328, 491 | 温和自然 |
| 👩 清亮女声 | 5555, 1455, 1518, 6666, 2345, 12345 | 甜美自然 |
| 👩 明亮女声 | 11, 5099, 125, 1234, 8888, 7777, 1111 | 清脆激昂 |
| 👩 高亮女声 | 3333, 5400, 12 | 高亢激昂 |

#### 其他后端

| 后端 | 部署方式 | 说明 |
|------|---------|------|
| **CosyVoice** | 本地 GPU | 阿里开源，多语言，音质好 |
| **Fish-Speech** | 本地 GPU | 开源，低延迟 |
| **ChatTTS** | 本地 Docker | 开源，37 种音色种子 |

### 10. 声线库（1000 种声线）

> 内置 1000 种声线 WAV 参考音频，一键选用到角色。

```bash
# 同步声线库（克隆仓库 + 生成索引）
drama voices

# 已有 WAV 文件？直接生成索引（不联网）
drama voices --index-only
```

**Web 工作台使用**：

1. 左侧导航 → 🎤 声线库
2. 搜索/筛选（性别、场景、风格）
3. ▶ 试听 → 选择合适的声线
4. 点击「选用」→ 选择角色 → 自动复制音频 + 更新角色 YAML

**存储**：

```
shared_assets/voices/          # 声线库（.gitignore 已屏蔽）
├── voices.json                # 索引（自动生成）
├── 001_汽车品牌广告_沉稳男声.wav
├── ...
└── 1000_第一千种声音_你的声音.wav
```

### 五阶段架构（推荐工作流）

> 以下所有操作均通过 Web 工作台完成（http://localhost:8888）

```
阶段1: AI 分镜（LLM，运行一次）
  └─ 从大纲生成分镜表 → DB

阶段2: AI 实体（LLM，运行一次）
  └─ 从分镜提取引用 → 批量生成缺失的角色/场景 → YAML

阶段3: 准备（LLM 密集，运行一次）
  ├─ 批量翻译 outfits/场景/分镜 → 写入 YAML *_en 字段
  └─ 视角 prompt 生成：appearance → appearance_prompt_en（AI 绘图格式）

阶段4: 生产（纯 GPU/本地，零 LLM 调用，全速）
  ├─ 定妆照 / 场景图（Web 工作台按需执行，或一键全流程自动执行）
  └─ TTS → 首帧 → 视频 → 口型同步

阶段5: 后期（纯本地）
  └─ 拼接 → 字幕 → 配乐 → 横转竖
```

**阶段职责分离**：每个阶段做一件事，失败时只需重试当前阶段。GPU 用户可灵活组合（如手动创建角色后跳过阶段 2）。

**收益**: 准备跑完后，生产完全不依赖 LLM，10 个镜头从 30-40 次 LLM 调用降为 0 次。

---

## 📖 CLI 命令

```bash
# 服务管理
drama serve                            # 启动 Web 工作台
drama worker                           # 启动 Celery Worker
drama worker -c 4                      # Worker 并发数 4
drama status                           # 服务状态（Redis + Celery + ComfyUI + TTS）
drama env                              # 环境信息（OS / Python / GPU / Redis）

# 数据导入导出
drama import plan.json                 # 从 JSON 导入剧本项目
drama import batch2.json --append      # 追加导入（解决 LLM 截断）
drama export 1                         # 导出分镜到 CSV
drama export 1 -o output.csv           # 指定输出路径

# 清理
drama clean --logs                     # 清理日志
drama clean --cache                    # 清理缓存

# 角色管理
drama outfit-regenerate <project> <char_id>   # 重新生成角色服装参考图
                                             # 用于调试服装图面部一致性（提高 PuLID 权重）

# 声线库
drama voices                           # 同步声线库
drama voices --index-only              # 已有 WAV 直接生成索引

# 环境预配置
drama setup --insightface              # 预下载 InsightFace buffalo_l 人脸检测模型
                                       # 避免 worker 任务中触发极慢的 GitHub 下载（~275MB）
```

> 所有生产操作（AI 生成、翻译、生产、后期、项目管理）均通过 Web 工作台完成。

---

## 🌐 Web 工作台

启动 `drama serve` 后访问 http://localhost:8888

| 页面 | 功能 |
|------|------|
| 📊 仪表盘 | 系统状态总览（Redis / Celery / ComfyUI / TTS / LipSync / LLM） |
| 👤 角色管理 | 创建/编辑/删除角色 + 🤖 AI 从描述生成 |
| 🏔️ 场景管理 | 创建/编辑/删除场景 + 🤖 AI 从描述生成 |
| 📝 分镜表 | 内联编辑表格 + 🤖 AI 从大纲一键生成 |
| 🎬 生产管线 | 五阶段执行：AI 分镜 → AI 实体 → 准备 → 生产 → 后期 |
| 📂 项目管理 | 多项目切换 |
| 🎤 声线库 | 搜索/试听/选用声线到角色 |
| ⚙️ 系统设置 | TTS/ComfyUI/LipSync/**LLM**/**Seko** 配置、语言切换 |

### 工作台快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Z` | 撤销 |
| `Ctrl+Shift+Z` / `Ctrl+Y` | 重做 |
| `ESC` | 关闭弹窗/预览 |

---

## 📚 API 文档

启动 Web 工作台后访问：
- **Swagger UI**: http://localhost:8888/docs
- **ReDoc**: http://localhost:8888/redoc

---

## 🏗️ 架构

```
┌─────────────┐     POST /api/pipeline/run     ┌──────────────┐
│   Web 前端   │ ──────────────────────────────→ │   FastAPI    │
│  (内联编辑)   │ ←────────────────────────────── │   (提交任务)  │
│  撤销/重做    │     { task_id, poll_url }        └──────┬───────┘
│  批量执行     │                                         │
│  资源预览     │     GET /api/tasks/{id}                 │ .delay()
│             │ ──────────────────────→                 ▼
│             │ ←──────────────┐              ┌──────────────────┐
└─────────────┘   { progress } │              │  Celery + Redis  │
                               │              │  (任务队列)       │
                               │              └────────┬─────────┘
                               │                       │
                               │              ┌────────▼─────────┐
                               └──────────────│  Celery Worker   │
                                              │  TTS / ComfyUI   │
                                              │  LipSync / FFmpeg│
                                              └──────────────────┘
```

**流程**: Web 提交 → Redis 队列 → Worker 执行 → 实时更新进度 → 前端轮询展示

### 后端懒加载

后端模块按需加载，缺依赖自动跳过不崩溃：

```
api/__init__.py (懒加载)
  ├─ tts/mimo_voicedesign  → 需要 httpx + MIMO_API_KEY
  ├─ tts/mimo_voiceclone   → 需要 httpx + MIMO_API_KEY
  ├─ tts/gpt_sovits        → 需要 httpx + 本地服务
  ├─ tts/cosyvoice         → 需要 httpx + 本地服务
  ├─ tts/fish_speech       → 需要 httpx + 本地服务
  ├─ tts/chattts           → 需要 httpx + 本地 ChatTTS-ui 服务
  ├─ lipsync/musetalk      → 需要 httpx + 本地服务
  ├─ lipsync/wav2lip       → 需要 httpx + 本地服务
  ├─ image/comfyui         → 需要 httpx + ComfyUI
  ├─ video/animatediff     → 需要 ComfyUI
  ├─ llm/ollama            → 需要 httpx + Ollama
  ├─ music/template        → 仅需 ffmpeg（无额外依赖）
  └─ music/musicgen        → 需要 httpx + MusicGen API（自部署或 RunPod）
```

### 注册表驱动

所有后端元数据集中在 `config/models_registry.yaml`，代码中零硬编码后端名：

```yaml
# 新增后端只需在注册表中声明，不改代码
image_backends:
  sd15:
    workflow: "01_first_frame_sd15.json"
    prompt_style: "tag"              # prompt 风格
    consistency_default: "ip_adapter" # 默认一致性方案
  flux:
    workflow: "01_first_frame_flux.json"
    prompt_style: "natural"
    consistency_default: "pulid_flux"

video_backends:
  animatediff:
    workflow: "02_img2video.json"
    frame_params:                    # 帧数注入规则
      node_class: "ADE_StandardStaticContextOptions"
      input_name: "context_length"

consistency_methods:                 # 一致性方案元数据
  ip_adapter:
    compatible_backends: ["sd15", "sdxl"]
    inject_method: "_inject_ip_adapter_plus"
    required_comfyui_node: "IPAdapterAdvanced"

services:                            # 辅助服务健康检查
  comfyui:
    health_check:
      type: "http"
      path: "/system_stats"
      config_key: "comfyui.url"
```

注册表覆盖范围：
- **TTS / LipSync / LLM / Music / Image / Video** — 所有后端的健康检查、默认值
- **prompt 风格** — `tag`（SD1.5 CLIP）或 `natural`（Flux/Cosmos T5）
- **一致性方案** — 与图像后端的兼容关系、注入方法、所需 ComfyUI 插件
- **帧数参数** — 视频后端的节点类型 + 参数名映射
- **生产步骤** — shot_task 的步骤编排
- **工具检测** — 健康检查类型驱动，零 if-elif

---

## ⚙️ 配置

编辑 `projects/<项目名>/config/project.yaml`：

```yaml
project:
  name: "我的短剧"
  episodes: 1
  fps: 24
  resolution: [1280, 720]
  style: "cinematic"
  genre: "urban"

comfyui:
  url: "http://127.0.0.1:8188"
  timeout: 300

models:
  tts_backend: "mimo-voicedesign"      # 云 API，开箱即用。本地部署可选: gpt-sovits / cosyvoice / fish-speech / chattts
  lip_sync_backend: "musetalk"
  music_backend: "template"            # ffmpeg 模板，无需额外服务
  # music_backend: "musicgen"          # MusicGen API（自部署或 RunPod），需配置 music.api_url
  image_backend: "sd15"
  video_backend: "animatediff"

  # 各后端配置
  musetalk:
    api_url: "http://your-musetalk-server:8080"
  gpt_sovits:
    api_url: "http://your-gpt-sovits-server:9880"  # 兼容 v1/v2 API，自动探测
  chattts:
    api_url: "http://your-chattts-server:7860"      # ChatTTS-ui Docker 部署

llm:
  enabled: false
  backend: "ollama"
  base_url: "http://localhost:11434"
  # model: "qwen3:8b"          # Ollama 模型名
  # api_key: ""                # OpenAI 兼容 API 需要
  batch_translate: true         # 批量翻译（多条合并一次 LLM 调用，false 则逐条翻译）

portraits:
  auto_outfit: true             # 管线中自动生成 outfit 参考图（默认 true）

timeouts:
  comfyui: 300
  tts: 60
  lipsync: 120
  llm: 300
  music: 120

seko:
  # api_key: ''  # 或设置环境变量 SEKO_API_KEY
```

### LLM 配置示例

```yaml
# Ollama（本地）
llm:
  enabled: true
  backend: "ollama"
  base_url: "http://localhost:11434"
  model: "qwen3:8b"

# SiliconFlow（云 API）
llm:
  enabled: true
  backend: "openai"
  base_url: "https://api.siliconflow.cn"
  model: "Qwen/Qwen2.5-7B-Instruct"
  api_key: "sk-xxx"

# OpenAI
llm:
  enabled: true
  backend: "openai"
  base_url: "https://api.openai.com"
  model: "gpt-4o-mini"
  api_key: "sk-xxx"
```

配置加载支持：
- 默认值自动合并
- mtime 缓存（修改后自动重载）
- 必填字段校验
- 数值范围校验

---

## 🧪 测试

```bash
# 运行全部测试（348 项）
pytest tests/ -v

# 分类运行
pytest tests/test_all.py -v           # 基础功能
pytest tests/test_api.py -v           # API 集成测试
pytest tests/test_celery.py -v        # Celery 任务测试
pytest tests/test_e2e.py -v           # 前端 E2E 测试
pytest tests/test_core.py -v          # 核心引擎测试
pytest tests/test_dialogue.py -v      # 对话解析测试
pytest tests/test_post.py -v          # 后期处理测试
pytest tests/test_session_changes.py -v  # 会话变更回归测试
pytest tests/test_append.py -v        # 追加导入测试
pytest tests/test_full_coverage.py -v # 覆盖率补充测试
```

---

## 📁 项目结构

```
ai-drama-pipeline/
├── cli/                          # CLI 入口（Click + Rich）
│   ├── __init__.py               #   主命令组 + 共享工具（Celery 轮询/环境检测）
│   ├── __main__.py               #   python -m cli 支持
│   ├── io.py                     #   import / export 命令
│   └── system.py                 #   serve / worker / status / env / clean 命令
├── pyproject.toml                # 依赖与构建配置
├── .env.example                  # 环境变量模板
│
├── api/                          # 后端层（懒加载 + DI 容器）
│   ├── __init__.py               # 懒加载注册（按 models_registry.yaml 动态导入）
│   ├── registry.py               # 服务注册表 + Container（DI 容器）
│   └── backends/                 # 后端实现
│       ├── tts/                  #   TTS: mimo_voicedesign / mimo_voiceclone / gpt_sovits / cosyvoice / fish_speech / chattts
│       ├── lipsync/              #   口型同步: musetalk / wav2lip
│       ├── image/                #   图像生成: comfyui（SD1.5/Flux/Cosmos/HiDream）
│       ├── video/                #   视频生成: animatediff（AnimateDiff/CogVideoX/Cosmos-Video）
│       ├── llm/                  #   LLM: ollama（Ollama + OpenAI 兼容）
│       ├── music/                #   配乐: template（FFmpeg）、musicgen（MusicGen API）
│       ├── seko/                 #   Seko 影视策划案
│       └── training/             #   LoRA 训练: ai_toolkit
│
├── engines/                      # 引擎层（核心业务逻辑）
│   ├── dialogue.py               #   对话解析
│   ├── quality_gate.py           #   质量门禁系统（管线各阶段自动检查）
│   ├── content/                  #   内容生成子包
│   │   ├── storyboard.py         #     分镜表加载/验证/保存（DB 为唯一数据源）
│   │   ├── llm.py                #     LLM 内容生成编排
│   │   ├── generator.py          #     LLM 内容生成器（分镜/角色/场景）
│   │   ├── portrait.py           #     定妆照生成（五视图 + 服装图）
│   │   ├── episode.py            #     集级状态管理
│   │   └── validator.py          #     实体校验
│   ├── prompt/                   #   Prompt 子包
│   │   ├── builder.py            #     Prompt 构建
│   │   ├── compiler.py           #     Mustache 风格模板编译器（从 prompt_templates.yaml 加载）
│   │   ├── translate.py          #     LLM 翻译（批量/单条）
│   │   └── view.py               #     Prompt 视图
│   ├── workflow/                 #   工作流子包
│   │   ├── builder.py            #     ComfyUI 工作流构建（首帧/视频，含 mtime 缓存）
│   │   ├── node_graph.py         #     工作流节点图
│   │   ├── utils.py              #     工作流工具
│   │   ├── inject.py             #     一致性方案注入（IP-Adapter/PuLID/LoRA）
│   │   ├── upload.py             #     资产上传
│   │   └── video.py              #     视频生成工作流
│   ├── consistency/              #   一致性子包
│   │   ├── bible.py              #     角色圣经系统（跨镜头一致性）
│   │   └── checker.py            #     分镜一致性校验（服装/角色/场景/情绪）
│   └── utils/                    #   工具子包
│       ├── entity.py             #     实体生成公共工具（统一角色/场景的生成+保存逻辑）
│       ├── multi_char.py         #     多人同框 prompt 处理
│       └── shot.py               #     镜头工具（后处理、文本清理、角色 ID 解析）
│
├── pipeline/                     # Celery 异步任务
│   ├── app.py                    #   Celery 配置 + 统一错误格式 + Worker 启动钩子
│   ├── portraits.py              #   定妆照批量生成
│   ├── scene_images.py           #   场景图批量生成
│   └── tasks/                    #   任务定义（按职责拆分）
│       ├── pipeline.py           #     管线编排（shot_task / produce / post / run_all）
│       ├── steps/                #     单镜头步骤模块
│       │   ├── tts.py            #       TTS 语音合成
│       │   ├── frame.py          #       首帧生成
│       │   ├── video.py          #       视频生成
│       │   └── lipsync.py        #       口型同步
│       ├── ai.py                 #     AI 生成（分镜/实体/准备/对话编辑）
│       ├── portrait.py           #     定妆照 / 场景图生成任务
│       ├── media.py              #     后期 / TTS / 配乐 / 字幕任务
│       ├── training.py           #     LoRA 训练 / JSON 导入任务
│       ├── preflight.py          #     预检任务
│       ├── prepare.py            #     准备阶段任务
│       ├── seko.py               #     Seko 策划案导入任务
│       └── helpers.py            #     共享工具（加载/校验/DB 记录/上下文缓存）
│
├── post/                         # 后期处理
│   ├── production.py             #   后期合成流水线（拼接→字幕→配乐→横转竖）
│   ├── subtitle.py               #   SRT 字幕生成
│   ├── music.py                  #   配乐生成（FFmpeg 模板）
│   └── vertical.py               #   横转竖（含人脸检测定位）
│
├── infra/                        # 基础设施
│   ├── constants.py              #   共享常量（情绪/景别/运镜/状态码/步骤名）
│   ├── globals.py                #   全局基础设施实例（看门狗/健康缓存/并发组）
│   ├── hooks.py                  #   后端钩子系统（init/cleanup/health_check/cache_invalidate）
│   ├── http_pool.py              #   HTTP 连接池（httpx，按 base_url+timeout 缓存）
│   ├── json_parse.py             #   LLM JSON 解析（容错：截断修复/代码块提取/单引号兼容）
│   ├── models.py                 #   共享数据模型（ImportPlan/ImportValidator/normalize_character）
│   ├── network.py                #   网络工具（端口检测）
│   ├── normalize.py              #   数据规范化
│   ├── toolcheck.py              #   工具可用性检测（注册表驱动，零 if-elif）
│   ├── transitions.py            #   转场拼接（xfade offset 精确计算）
│   ├── validation.py             #   输入校验
│   ├── compute/                  #   计算子包
│   │   ├── ffmpeg.py             #     FFmpeg 封装（链式 API）
│   │   └── gpu.py                #     GPU / 生成参数配置
│   ├── concurrency/              #   并发控制子包
│   │   ├── batch.py              #     自适应批处理器（三重约束分批 + 错误驱动学习）
│   │   ├── executor.py           #     安全执行器（任务级错误边界 + 超时 + 降级）
│   │   ├── groups.py             #     并发组（互斥锁按资源组管理）
│   │   └── monitor.py            #     任务监控（超时检测 + 空闲淘汰 + 健康检查缓存）
│   ├── config/                   #   配置子包
│   │   ├── core.py               #     配置管理核心（mtime 缓存 + 热重载 + 注册表默认值合并）
│   │   ├── cache.py              #     配置缓存
│   │   ├── loader.py             #     配置加载器
│   │   ├── paths.py              #     路径管理
│   │   ├── registry.py           #     模型注册表
│   │   ├── registry_llm.py       #     LLM 注册表
│   │   ├── registry_media.py     #     媒体注册表
│   │   └── resolver.py           #     配置解析器
│   ├── storage/                  #   存储子包
│   │   ├── asset_tracker.py      #     ComfyUI 资产跟踪（PostgreSQL 持久化）
│   │   └── file_watcher.py       #     文件系统监控（YAML 变化自动失效缓存）
│   └── database/                 #   PostgreSQL（分镜表/生成状态/资产跟踪）
│       ├── schema.py             #     表结构定义（CREATE IF NOT EXISTS）
│       ├── pool.py               #     连接池（ThreadedConnectionPool）
│       ├── _db.py                #     共享工具（项目自动解析 + query 上下文管理器）
│       ├── storyboard_db.py      #     分镜 CRUD + CSV 导出
│       ├── generation.py         #     生成状态 CRUD
│       └── comfyui_assets.py     #     ComfyUI 资产跟踪表
│
├── web/                          # FastAPI Web 工作台
│   ├── app.py                    #   应用工厂 + 日志配置 + lifespan
│   ├── services/__init__.py      #   日志配置服务
│   ├── schemas/__init__.py       #   Pydantic 请求/响应模型（25+ 个 Schema）
│   ├── routers/                  #   API 路由（按领域拆分）
│   │   ├── api.py                #     路由聚合入口
│   │   ├── system_tools.py       #     系统状态 / 工具管理 / 配置 / 单步执行（26 路由）
│   │   ├── characters.py         #     角色 CRUD + 定妆照生成（7 路由）
│   │   ├── scenes.py             #     场景 CRUD + 场景图生成（5 路由）
│   │   ├── storyboard.py         #     分镜表 / 集数 / 管线 / LLM 生成（18 路由）
│   │   ├── assets.py             #     资产上传/下载/共享库（7 路由）
│   │   ├── imports.py            #     项目管理 / 导入 / Seko / 训练（14 路由）
│   │   ├── voices.py             #     声线库（列表/试听/分配，3 路由）
│   │   └── deps.py               #     共享依赖（配置访问/校验/任务提交/YAML CRUD）
│   └── static/                   #   前端 SPA
│       ├── index.html            #     单页应用（9 个页面：仪表盘/角色/场景/分镜/管线/项目/资产/Seko/设置）
│       ├── css/style.css         #     样式
│       ├── js/                   #     JS 模块（15 个：core/app/i18n/dashboard/characters/scenes/storyboard/pipeline/projects/tasks/settings/ai-gen/seko/extras/voices）
│       └── favicon.svg
│
├── scripts/                      # 工具脚本
│   ├── project_mgr.py            #   项目管理（新建/切换/删除/预设列表）
│   ├── project_builder.py        #   项目构建器（JSON 导入时原子性创建项目）
│   ├── ai_toolkit_api.py         #   AI Toolkit 训练 API 客户端
│   ├── musicgen_server.py        #   MusicGen API 服务器
│   └── voice_sync.py             #   声线库同步（克隆仓库 + 生成索引）
│
├── tests/                        # 测试（15 个测试文件）
│   ├── conftest.py               #   共享 fixtures + 环境检测
│   ├── test_all.py               #   基础功能测试
│   ├── test_api.py               #   API 集成测试
│   ├── test_append.py            #   追加导入测试
│   ├── test_celery.py            #   Celery 任务测试
│   ├── test_core.py              #   核心引擎测试
│   ├── test_dialogue.py          #   对话解析测试
│   ├── test_e2e.py               #   前端 E2E 测试
│   ├── test_full_coverage.py     #   覆盖率补充测试
│   ├── test_import_e2e_standalone.py  # 导入 E2E 测试
│   ├── test_import_standalone.py #   导入测试
│   ├── test_node_graph.py        #   节点图测试
│   ├── test_p2_review.py         #   P2 审查测试
│   ├── test_post.py              #   后期处理测试
│   └── test_session_changes.py   #   会话变更回归测试
│
├── config/                       # 全局配置
│   ├── system.yaml               #   系统全局配置（ComfyUI/LLM/TTS/一致性方案/预设）
│   ├── models_registry.yaml      #   模型注册表（所有后端元数据的唯一真相来源）
│   ├── prompt_templates.yaml     #   Prompt 模板（翻译/分镜/角色/场景/圣经生成）
│   └── default_storyboard.py     #   默认分镜种子数据
│
├── workflows/                    # ComfyUI 工作流模板（8 个 JSON）
│   ├── 01_first_frame_sd15.json  #   SD1.5 首帧
│   ├── 01_first_frame_flux.json  #   Flux 首帧
│   ├── 01_first_frame_flux_fp8.json  # Flux FP8 首帧
│   ├── cosmos_predict2_2B_t2i.json   # Cosmos 首帧
│   ├── 02_img2video.json         #   AnimateDiff 视频
│   ├── 03_img2video_cogvideo.json    # CogVideoX 视频
│   ├── 04_img2video_cosmos.json  #   Cosmos 视频
│   └── 05_img2img_hidream.json   #   HiDream img2img
│
├── shared_assets/                # 全局共享资产（.gitignore 屏蔽）
│   └── voices/                   #   声线库（drama voices 同步）
│
├── projects/                     # 项目目录（每个短剧独立）
│   ├── .active                   #   当前活动项目指针
│   ├── default/                  #   默认项目模板
│   │   ├── config/
│   │   │   ├── project.yaml      #     项目配置
│   │   │   ├── characters/       #     角色配置
│   │   │   └── scenes/           #     场景配置
│   │   ├── assets/               #     资产（定妆照/场景图/LoRA）
│   │   └── output/               #     生成产物
│   └── <你的项目名>/             #   新建项目（结构同上）
│
└── docs/                         # 文档
    ├── pipeline.md               #   管线全流程架构详解
    ├── PROJECT_FLOWCHART.md      #   项目流程总览
    ├── musicgen-deploy.md        #   MusicGen 部署指南
    └── internal/
        └── script-import-design.md   # 剧本导入功能设计文档
```

---

## 🔧 常见问题排查

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| `Redis 未运行` | Redis 服务未启动 | `redis-server --daemonize yes` 或 `brew services start redis` |
| `AI_DRAMA_DB_DSN 未配置` | 缺少 `.env` 文件 | `cp .env.example .env` 并填写 PostgreSQL 连接信息 |
| `PostgreSQL 连接被拒绝` | PostgreSQL 未启动 | 见下方「PostgreSQL 启动方式」 |
| `PostgreSQL 认证失败` | 用户名/密码不匹配 | 检查 `.env` 中的 `AI_DRAMA_DB_DSN`，确认用户和密码 |
| `数据库不存在` | 未创建 ai_drama 数据库 | `sudo -u postgres psql -c "CREATE DATABASE ai_drama OWNER drama;"` |
| `Celery Worker 未启动` | Worker 进程未运行 | 在另一个终端运行 `drama worker` |
| `ComfyUI 不可达` | ComfyUI 未启动或地址错误 | 确认 ComfyUI 已启动：`curl http://127.0.0.1:8188/system_stats`。安装：[ComfyUI](https://github.com/comfyanonymous/ComfyUI) |
| `MIMO_API_KEY 未设置` | 缺少 TTS API Key | 在 `.env` 中填写 `MIMO_API_KEY=`（免费获取：https://api.xiaomimimo.com） |
| `LLM 未启用` | LLM 配置未开启 | 在项目配置中设置 `llm.enabled: true`，或在 Web 设置页开启 |
| `角色缺定妆照` | 未生成角色形象图 | Web 工作台「👤 角色」→「🎨 AI 生成定妆照」 |
| `请先执行准备阶段` | 生产前未翻译 | Web 工作台「🎬 生产管线」→「🔧 准备阶段」 |

#### PostgreSQL 启动方式

不同环境下 PostgreSQL 启动命令不同，按顺序尝试：

**方式一：pg_ctlcluster（Debian/Ubuntu）**

```bash
# 查看已安装的 PostgreSQL 版本
ls /etc/postgresql/

# 启动对应版本（替换 <version> 为实际版本号，如 16）
sudo pg_ctlcluster <version> main start

# 例如 PostgreSQL 16：
sudo pg_ctlcluster 16 main start
```

**方式二：systemctl（大多数 Linux 发行版）**

```bash
sudo systemctl start postgresql
```

**方式三：macOS（Homebrew）**

```bash
brew services start postgresql@16
```

**方式四：Docker**

```bash
docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=drama123 -e POSTGRES_USER=drama -e POSTGRES_DB=ai_drama postgres:16-alpine
```

> **启动后验证**：`sudo -u postgres psql -c "SELECT 1;"` 返回 `1` 表示 PostgreSQL 正常运行。

---

## 🔒 安全

本项目面向**个人本地使用**，安全措施以实用为主，不做过度防护。

已有的安全机制：
- **输入校验**: Pydantic 模型校验 API 请求（ID 格式、数值范围、文本长度）
- **路径遍历防护**: `_safe_path()` 阻断 `../` 攻击
- **任务 ID 校验**: UUID 格式验证

> 个人部署场景下，速率限制（60s/300 次）等功能不构成实际需求。如需暴露到公网，请自行在前端加 Nginx 反向代理并配置认证。

---

## 📝 License

MIT
