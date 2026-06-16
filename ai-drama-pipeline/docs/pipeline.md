# 🎬 AI 短剧管线 — 全流程架构

> 从剧本到成片，五阶段生产管线详解

---

## 全局总览

```mermaid
flowchart TB
    subgraph S1["📝 阶段 1 · AI 分镜 — LLM，运行一次"]
        outline[("剧情大纲")] -->|LLM| gen_sb["🎬 分镜表<br/>PostgreSQL shots 表"]
    end

    subgraph S2["👥 阶段 2 · AI 实体 — LLM，运行一次"]
        gen_sb2["分镜表"] -->|LLM| gen_chars["👤 角色配置<br/>characters/*.yaml"]
        gen_sb2 -->|LLM| gen_scenes["🏔️ 场景配置<br/>scenes/*.yaml"]
    end

    subgraph S3["🔧 阶段 3 · 准备 — LLM 密集，运行一次"]
        direction TB
        t["3.1 批量翻译<br/>appearance→en, description→en<br/>action→en, dialogue→en"]
    end

    subgraph S3p["📸 定妆照 / 场景图"]
        direction TB
        p["3.2 定妆照<br/>Web 工作台单独执行<br/>📸 定妆照按钮"]
        si["3.3 场景图<br/>Web 工作台单独执行<br/>🏔️ 场景图按钮"]
    end

    subgraph S4["🎬 阶段 4 · 生产 — 纯 GPU，零 LLM"]
        direction TB
        loop["逐镜头循环<br/>TTS → 首帧 → 视频 → 口型同步"]
    end

    subgraph S5["🎉 阶段 5 · 后期"]
        post2["拼接 → 字幕 → 配乐 → 横转竖"]
        final["episode_01_final.mp4"]
        post2 --> final
    end

    S1 ==> S2 ==> S3 ==> S3p ==> S4 ==> S5

    style S1 fill:#2d1b69,stroke:#7c3aed,color:#e2e8f0
    style S2 fill:#1b3b4b,stroke:#0891b2,color:#e2e8f0
    style S3 fill:#1b2e4b,stroke:#2563eb,color:#e2e8f0
    style S3p fill:#1b3b2e,stroke:#059669,color:#e2e8f0
    style S4 fill:#1b3b2e,stroke:#059669,color:#e2e8f0
    style S5 fill:#3b2e1b,stroke:#d97706,color:#e2e8f0
```

---

## 阶段 1 · AI 分镜

> 从大纲生成分镜表。已有角色/场景时自动注入 prompt 提升质量。

| 操作 | Web 工作台路径 | 依赖 |
|------|----------------|------|
| 生成分镜表 | 「📝 分镜表」→「🤖 AI 生成」 | LLM |

**产出：**
- PostgreSQL 数据库 — 分镜表（shots 表）

**注意：** 分镜生成后，会提示引用了哪些未创建的角色/场景。请执行阶段 2 生成。

---

## 阶段 2 · AI 实体

> 从分镜提取引用的角色/场景，批量 AI 生成缺失的配置。只生成缺失的，不覆盖已有。

```mermaid
flowchart LR
    sb["分镜表<br/>shots 表"] -->|提取引用| ids["角色/场景 ID"]
    ids -->|过滤已有| missing["缺失的实体"]
    missing -->|LLM| chars["角色配置<br/>characters/*.yaml"]
    missing -->|LLM| scenes["场景配置<br/>scenes/*.yaml"]

    style sb fill:#1e293b,stroke:#334155,color:#e2e8f0
    style missing fill:#2d1b69,stroke:#7c3aed,color:#c4b5fd
    style chars fill:#1e293b,stroke:#334155,color:#e2e8f0
    style scenes fill:#1e293b,stroke:#334155,color:#e2e8f0
```

| 操作 | Web 工作台路径 | 依赖 |
|------|----------------|------|
| AI 生成角色/场景 | 「🎬 生产管线」→「👥 AI 生成角色/场景」 | LLM |
| 手动创建角色 | 「👤 角色」→「+ 新建」 | 无 |
| 手动创建场景 | 「🏔️ 场景」→「+ 新建」 | 无 |

**产出文件：**
- `projects/<项目>/config/characters/*.yaml` — 角色配置（唯一数据源）
- `projects/<项目>/config/scenes/*.yaml` — 场景配置（唯一数据源）

**两种路径：**
- **快速起步**：分镜 → AI 实体 → 准备 → 生产（零配置）
- **精细化**：手动创建角色/场景 → 分镜（注入已有实体） → 补充缺失 → 准备 → 生产

---

## 阶段 3 · 准备

> 批量翻译集中完成。运行一次后，生产管线 **零 LLM 调用**。角色圣经（character bible）通过 Web 工作台「📝 分镜表」→「🤖 AI 生成角色圣经」生成。

#### 执行顺序

```
progress 10%  扫描角色/场景/分镜
progress 40%  批量翻译（outfits/场景/分镜的 _en 字段）
progress 80%  回写翻译结果到 YAML + DB
progress 90%  视角 prompt 生成（appearance → appearance_prompt_en）
progress 100% 完成
```

> **注意**：`appearance`（角色外貌）不参与批量翻译，由视角 prompt 生成步骤专门处理。
> 该步骤将中文外貌描述直接转换为 AI 绘图专用 prompt（含性别标签、体型关键词等），
> 避免"先翻译再格式化"的两次 LLM 调用互相覆盖。

```mermaid
flowchart TB
    subgraph translate["3.1 批量翻译 — LLM（progress 40%）"]
        direction TB
        tc["角色翻译<br/>outfits.*.description → description_en<br/>bible 字段 → bible_en"]
        ts["场景翻译<br/>description → description_en<br/>lighting → lighting_en"]
        tb["分镜翻译<br/>action → action_en<br/>dialogue → dialogue_en"]
    end

    subgraph viewprompt["3.2 视角 prompt 生成 — LLM（progress 90%）"]
        direction TB
        vp["角色外貌 → AI 绘图 prompt<br/>appearance (中文) → appearance_prompt_en<br/>+ body_features (伤疤/纹身提取)"]
    end

    subgraph portraits["3.3 定妆照 — ComfyUI（Web 端单独执行）"]
        direction TB
        pm["主定妆照<br/>特写构图"]
        po["服装参考图<br/>全身构图 × N 套"]
        pm --> po
    end

    subgraph scenes_gen["3.4 场景图 — ComfyUI（Web 端单独执行）"]
        direction TB
        sg["全景参考图<br/>读取 description_en"]
    end

    translate --> viewprompt
    viewprompt -.->|"可选: --portraits"| portraits
    viewprompt -.->|"可选: --scene-images"| scenes_gen

    yaml1["YAML 文件<br/>reference_images 回写<br/>（唯一数据源）"]
    portraits --> yaml1
    scenes_gen --> yaml1

    style translate fill:#1e293b,stroke:#2563eb,color:#93c5fd
    style viewprompt fill:#2d1b69,stroke:#7c3aed,color:#c4b5fd
    style portraits fill:#1e293b,stroke:#059669,color:#6ee7b7
    style scenes_gen fill:#1e293b,stroke:#059669,color:#6ee7b7
```

| 操作 | Web 工作台路径 | 依赖 |
|------|----------------|------|
| 批量翻译 + 视角 prompt | 「🎬 生产管线」→「🔧 准备阶段」 | LLM |
| 强制重新生成（覆盖已有） | 同上，勾选「强制覆盖」 | LLM |

> 定妆照和场景图通过 Web 工作台「📸 定妆照」「🏔️ 场景图」单独执行，支持单角色/单场景按需生成。

### 翻译策略

```mermaid
flowchart LR
    input["中文文本<br/>outfits / description / action ..."] --> check{"文本含<br/>中文字符？"}
    check -->|否| skip["跳过翻译<br/>已是英文"]
    check -->|是| check_en{"*_en 字段<br/>已有值？"}
    check_en -->|是| use["使用已有值"]
    check_en -->|否| translate["LLM 翻译<br/>中→英"]
    translate --> write["写入 *_en 字段"]

    style input fill:#1e293b,stroke:#334155,color:#e2e8f0
    style translate fill:#2d1b69,stroke:#7c3aed,color:#c4b5fd
    style write fill:#1e293b,stroke:#2563eb,color:#93c5fd
```

### 收益

| 场景 | 无 prepare | 有 prepare |
|------|-----------|-----------|
| 10 个镜头 | 30-40 次 LLM 调用 | **0 次** LLM 调用 |
| 生产速度 | 受 LLM 延迟限制 | **纯 GPU 全速** |

---

## 阶段 4 · 生产

> 纯 GPU/本地执行，零 LLM 调用。逐镜头完成 TTS → 首帧 → 视频 → 口型同步。**不含后期合成**（后期由 Web 工作台「📦 后期合成」独立处理）。

```mermaid
flowchart TB
    subgraph produce["镜头生产 — Web 工作台「🎬 生产管线」→「▶ 生产」"]
        direction TB

        subgraph step0["4.0 生成字幕"]
            srt["读取分镜 dialogue<br/>→ episode_01.srt"]
        end

        subgraph loop["4.1 逐镜头循环"]
            direction LR
            subgraph shot["单镜头处理流程"]
                direction LR
                s1["🗣️ TTS 合成<br/>────<br/>台词文本<br/>+ 角色声音配置<br/>→ audio.wav<br/><br/>[MIMO TTS 云API]"]
                s2["🖼️ 首帧生成<br/>────<br/>appearance_en<br/>+ description_en<br/>+ LoRA (可选)<br/>→ frame.png<br/><br/>[ComfyUI]"]
                s3["🎥 视频生成<br/>────<br/>frame.png<br/>+ duration→帧数<br/>→ video.mp4<br/><br/>[AnimateDiff]"]
                s4["👄 口型同步<br/>────<br/>video.mp4<br/>+ audio.wav<br/>→ synced.mp4<br/><br/>[MuseTalk]"]
                s1 --> s2 --> s3 --> s4
            end
        end

        step0 ==> loop
    end

    style step0 fill:#1e293b,stroke:#334155,color:#94a3b8
    style loop fill:#0f172a,stroke:#059669,color:#e2e8f0
    style shot fill:#1e293b,stroke:#334155,color:#e2e8f0
```

### 单镜头四步详解

```mermaid
flowchart LR
    subgraph step1["Step 1: TTS"]
        direction TB
        t_in["输入<br/>────<br/>dialogue: 你好吗<br/>voice_config: 女声温柔<br/>emotion: happy<br/>language: zh"]
        t_out["输出<br/>────<br/>audio.wav"]
        t_in --> t_out
    end

    subgraph step2["Step 2: 首帧"]
        direction TB
        f_in["输入<br/>────<br/>appearance_en: young woman...<br/>description_en: modern living room...<br/>shot_type: 特写<br/>参考图 (可选)"]
        f_out["输出<br/>────<br/>frame.png"]
        f_in --> f_out
    end

    subgraph step3["Step 3: 视频"]
        direction TB
        v_in["输入<br/>────<br/>frame.png<br/>duration: 4s → 96帧"]
        v_out["输出<br/>────<br/>video.mp4"]
        v_in --> v_out
    end

    subgraph step4["Step 4: 口型"]
        direction TB
        l_in["输入<br/>────<br/>video.mp4<br/>audio.wav"]
        l_out["输出<br/>────<br/>synced.mp4"]
        l_in --> l_out
    end

    step1 --> step2 --> step3 --> step4

    style step1 fill:#1e293b,stroke:#334155,color:#e2e8f0
    style step2 fill:#1e293b,stroke:#334155,color:#e2e8f0
    style step3 fill:#1e293b,stroke:#334155,color:#e2e8f0
    style step4 fill:#1e293b,stroke:#334155,color:#e2e8f0
```

### produce 内部子步骤与进度

| 步骤 | 进度 | 说明 |
|------|------|------|
| 4.0 生成字幕 | 0-5% | 读分镜 dialogue → SRT 文件 |
| 4.1 逐镜头循环 | 5-100% | 每个镜头: TTS → 首帧 → 视频 → 口型 |

---

## 阶段 5 · 后期

> 后期合成通过 Web 工作台「🎬 生产管线」→「📦 后期合成」执行，用于**重做后期**而不重新生成镜头。

```mermaid
flowchart LR
    subgraph input["输入"]
        v1["s001/synced.mp4"]
        v2["s002/synced.mp4"]
        v3["s003/synced.mp4"]
        vn["sN/synced.mp4"]
        srt["episode_01.srt"]
        bgm["bgm.wav"]
    end

    subgraph process["处理流程"]
        direction LR
        concat["✂️ FFmpeg 拼接<br/>crossfade 转场<br/>transition_duration: 0.5s"]
        subtitle["📝 字幕叠加<br/>SRT 烧录到画面"]
        music["🎵 配乐混合<br/>BGM 音量 0.15"]
        vertical["📱 横转竖<br/>9:16 人脸追踪"]
        concat --> subtitle --> music --> vertical
    end

    subgraph output["输出"]
        final["episode_01_final.mp4"]
    end

    input --> process --> output

    style input fill:#1e293b,stroke:#334155,color:#94a3b8
    style process fill:#1e293b,stroke:#d97706,color:#fcd34d
    style output fill:#3b2e1b,stroke:#d97706,color:#fcd34d
```

| 操作 | Web 工作台路径 |
|------|----------------|
| 后期合成（横屏） | 「🎬 生产管线」→「📦 后期合成」 |
| 后期合成 + 横转竖 | 同上，勾选「横转竖」 |

---

## Web 工作台操作流程

```mermaid
flowchart LR
    subgraph entities["👥 AI 实体"]
        direction TB
        e1["从分镜提取引用<br/>批量生成缺失实体"]
    end

    subgraph prep["🔧 准备阶段"]
        direction TB
        p1["批量翻译<br/>LLM 密集"]
    end

    subgraph prod["▶ 生产"]
        direction TB
        po1["字幕 SRT"]
        po2["逐镜头循环<br/>TTS→首帧→视频→口型"]
        po1 --> po2
    end

    subgraph post["📦 后期合成"]
        direction TB
        pt1["拼接→字幕→配乐→横转竖"]
    end

    subgraph all["🚀 一键全流程"]
        direction TB
        a1["AI 实体"]
        a2["准备"]
        a2p["定妆照"]
        a3["生产"]
        a4["后期"]
        a1 --> a2 --> a2p --> a3 --> a4
    end

    style entities fill:#1b3b4b,stroke:#0891b2,color:#67e8f9
    style prep fill:#1e293b,stroke:#334155,color:#94a3b8
    style prod fill:#1b3b2e,stroke:#059669,color:#6ee7b7
    style post fill:#1e293b,stroke:#d97706,color:#fcd34d
    style all fill:#1b2e4b,stroke:#2563eb,color:#93c5fd
```

| 操作 | 说明 |
|------|------|
| 「👥 AI 生成角色/场景」 | 从分镜提取引用，批量生成缺失实体（LLM） |
| 「🔧 准备阶段」 | 批量翻译（LLM 密集，运行一次即可） |
| 「▶ 生产」 | 镜头生产（纯 GPU，零 LLM） |
| 「📦 后期合成」 | 拼接、字幕、配乐、横转竖 |
| 「🚀 一键全流程」 | AI 实体 → 准备 → 定妆照 → 生产 → 后期 |

---

## 数据流全景

```mermaid
flowchart TB
    subgraph files["项目文件结构"]
        direction TB
        yaml_c["config/characters/*.yaml<br/>角色: appearance, appearance_en,<br/>outfits, voice, reference_images<br/>（唯一数据源）"]
        yaml_s["config/scenes/*.yaml<br/>场景: description, description_en,<br/>lighting, reference_images<br/>（唯一数据源）"]
        db_sb[("PostgreSQL shots 表<br/>分镜: action, action_en,<br/>dialogue, dialogue_en, shot_type, ...<br/>（唯一数据源）")]
        assets_c["assets/characters/<br/>角色定妆照 + outfit 参考图"]
        assets_s["assets/scenes/<br/>场景参考图"]
        output["output/e01/s001/<br/>audio.wav, frame.png,<br/>video.mp4, synced.mp4"]
        final["output/e01/<br/>episode_01_final.mp4"]
    end

    subgraph stages["处理阶段"]
        direction LR
        s1["阶段1: LLM 分镜"]
        s2["阶段2: LLM 实体"]
        s3t["阶段3.1: LLM 翻译"]
        s3p["阶段3.2: ComfyUI 定妆照"]
        s3s["阶段3.3: ComfyUI 场景图"]
        s4t["阶段4: TTS"]
        s4f["阶段4: ComfyUI 首帧"]
        s4v["阶段4: ComfyUI 视频"]
        s4l["阶段4: LipSync"]
        s5["阶段5: FFmpeg 后期"]
    end

    s1 -->|"生成"| db_sb
    s2 -->|"生成"| yaml_c & yaml_s
    s3t -->|"翻译写入 *_en"| yaml_c & yaml_s & db_sb
    s3p -->|"生成图片"| assets_c
    s3s -->|"生成图片"| assets_s
    yaml_c & yaml_s -->|"读取 *_en"| s4f
    db_sb -->|"读取 dialogue"| s4t
    s4t -->|"audio.wav"| output
    s4f -->|"frame.png"| output
    s4v -->|"video.mp4"| output
    s4l -->|"synced.mp4"| output
    output -->|"拼接"| s5
    s5 -->|"final.mp4"| final

    style files fill:#0f172a,stroke:#334155,color:#e2e8f0
    style stages fill:#0f172a,stroke:#334155,color:#94a3b8
```

---

## 角色面部一致性

> 通过 `consistency_method` 配置项选择一致性方案，与图像后端独立解耦

### 配置

```yaml
# config/system.yaml
consistency_method: auto   # auto / pulid_flux / ip_adapter / none
```

| 值 | 说明 | 适用后端 |
|----|------|---------|
| `auto` | 根据 image_backend 自动选择 | flux→pulid, sd15→ip_adapter, cosmos→none |
| `pulid_flux` | PuLID-Flux 面部一致性 | Flux（DiT） |
| `ip_adapter` | IP-Adapter Plus 面部一致性 | SD1.5/SDXL（UNet） |
| `none` | 不使用一致性（仅 LoRA + seed） | 全部 |

### PuLID-Flux（Flux 后端推荐）

> InsightFace 检测人脸 → EVA CLIP 编码 → 注入 Flux DiT 注意力层

```mermaid
flowchart LR
    subgraph input["输入"]
        ref["📸 定妆照<br/>cover.png"]
        prompt["📝 Prompt<br/>appearance_en"]
    end

    subgraph pulid["PuLID-Flux 链"]
        direction TB
        pid["LoadPuLIDFluxModel<br/>pulid_flux_v0.9.0.safetensors"]
        face["LoadInsightFace<br/>AntelopeV2"]
        eva["LoadEvaClip<br/>EVA02-CLIP-L-14-336"]
        apply["ApplyPuLIDFlux<br/>weight=0.9<br/>fusion=mean"]
        ref --> apply
        pid --> apply
        face --> apply
        eva --> apply
    end

    subgraph gen["生成"]
        ks["KSampler"]
        out["🖼️ 首帧"]
    end

    prompt --> ks
    apply -->|"model"| ks
    ks --> out

    style pulid fill:#1b2e4b,stroke:#2563eb,color:#e2e8f0
    style gen fill:#1b3b2e,stroke:#059669,color:#6ee7b7
```

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `pulid_flux.model` | `pulid_flux_v0.9.0.safetensors` | PuLID Flux 模型 |
| `pulid_flux.weight` | `0.9` | 面部权重（推荐 0.8-0.95，1.0 过拟合） |
| `pulid_flux.fusion` | `mean` | 多图融合: mean / concat / max / train_weight |
| `pulid_flux.use_gray` | `true` | 灰度优化（边缘轮廓更自然） |

### IP-Adapter Plus（SD1.5/SDXL 后端）

> CLIP Vision 编码参考图 → IP-Adapter 注入 UNet cross-attention 层

```mermaid
flowchart LR
    subgraph input["输入"]
        ref["📸 定妆照<br/>cover.png"]
        prompt["📝 Prompt<br/>appearance_en"]
    end

    subgraph ipa["IP-Adapter Plus 链"]
        direction TB
        ipmodel["IPAdapterModelLoader<br/>ip-adapter-plus-face_sd15"]
        clipvis["CLIPVisionLoader<br/>CLIP-ViT-H-14"]
        ipadv["IPAdapterAdvanced<br/>weight=0.75<br/>embeds_scaling=V only"]
        ref --> ipadv
        ipmodel --> ipadv
        clipvis --> ipadv
    end

    subgraph gen["生成"]
        ks["KSampler"]
        out["🖼️ 首帧"]
    end

    prompt --> ks
    ipadv -->|"model"| ks
    ks --> out

    style ipa fill:#2d1b69,stroke:#7c3aed,color:#e2e8f0
    style gen fill:#1b3b2e,stroke:#059669,color:#6ee7b7
```

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `ip_adapter.model` | `ip-adapter-plus-face_sd15.safetensors` | 面部一致性最佳 |
| `ip_adapter.weight` | `0.75` | 参考图影响力（0-1） |
| `ip_adapter.embeds_scaling` | `V only` | 面部特征保持最佳 |
| `ip_adapter.secondary_weight` | `0.45` | 多角色时次要角色权重 |

**多角色同框**：两种方案均自动链式注入，主角色高权重，次要角色自动降权。

---

## 服务依赖

```mermaid
flowchart LR
    subgraph required["必选"]
        redis["Redis<br/>任务队列"]
        pg["PostgreSQL<br/>状态存储"]
        celery["Celery Worker<br/>异步执行"]
    end

    subgraph production["生产阶段"]
        tts["TTS 服务<br/>MIMO / GPT-SoVITS / CosyVoice"]
        comfyui["ComfyUI<br/>图片+视频生成"]
        lipsync["LipSync<br/>MuseTalk / Wav2Lip"]
        ipadapter["IP-Adapter Plus<br/>角色面部一致性"]
    end

    subgraph optional["可选"]
        llm["LLM 服务<br/>Ollama / OpenAI 兼容"]
        seko["Seko 策划案<br/>seko.sensetime.com"]
        ffmpeg["FFmpeg<br/>后期合成"]
    end

    redis --> celery
    celery --> tts & comfyui & lipsync
    comfyui --> ipadapter
    llm -.->|"阶段1-3"| celery
    seko -.->|"策划案导入"| celery
    ffmpeg -.->|"阶段5"| celery

    style required fill:#1b3b2e,stroke:#059669,color:#6ee7b7
    style production fill:#1b2e4b,stroke:#2563eb,color:#93c5fd
    style optional fill:#1e293b,stroke:#334155,color:#94a3b8
```

---

## 快速参考

```
首次使用:
1. 启动服务: drama serve + drama worker
2. Web 工作台生成内容（大纲 → 分镜 → AI 实体）
3. 准备阶段（批量翻译）
4. 生成定妆照 + 场景图
5. 生产 → 后期 → 成片

服务管理:
  drama serve    — 启动 Web 工作台
  drama worker   — 启动 Celery Worker
  drama status   — 查看服务状态
```
