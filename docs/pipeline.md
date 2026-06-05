# 🎬 AI 短剧管线 — 全流程架构

> 从剧本到成片，四阶段生产管线详解

---

## 全局总览

```mermaid
flowchart TB
    subgraph S0["📝 阶段 0 · 内容生成"]
        outline[("剧情大纲")] -->|LLM| gen_chars["👤 角色配置<br/>characters/*.yaml"]
        outline -->|LLM| gen_scenes["🏔️ 场景配置<br/>scenes/*.yaml"]
        outline -->|LLM| gen_sb["🎬 分镜表<br/>PostgreSQL shots 表"]
    end

    subgraph S1["🔧 阶段 1 · 准备 — LLM 密集，运行一次"]
        direction TB
        t["1.1 批量翻译<br/>appearance→en, description→en<br/>action→en, dialogue→en"]
        p["1.2 定妆照<br/>Web 工作台单独执行<br/>📸 定妆照按钮"]
        si["1.3 场景图<br/>Web 工作台单独执行<br/>🏔️ 场景图按钮"]
        t -.->|"可选"| p
        t -.->|"可选"| si
    end

    subgraph S2["🎬 阶段 2 · 生产 — 纯 GPU，零 LLM"]
        direction TB
        sub["2.0 生成字幕 SRT"]
        loop["2.1 逐镜头循环<br/>TTS → 首帧 → 视频 → 口型同步"]
        sub --> loop
    end

    subgraph S3["🎉 阶段 3 · 后期"]
        post2["拼接 → 字幕 → 配乐 → 横转竖"]
        final["episode_01_final.mp4"]
        post2 --> final
    end

    S0 ==> S1 ==> S2 ==> S3

    style S0 fill:#2d1b69,stroke:#7c3aed,color:#e2e8f0
    style S1 fill:#1b2e4b,stroke:#2563eb,color:#e2e8f0
    style S2 fill:#1b3b2e,stroke:#059669,color:#e2e8f0
    style S3 fill:#3b2e1b,stroke:#d97706,color:#e2e8f0
```

---

## 阶段 0 · 内容生成（可选）

> 从大纲自动生成角色、场景、分镜。已有素材可跳过。

```mermaid
flowchart LR
    outline["📄 剧情大纲"] -->|LLM| storyboard["分镜表<br/>PostgreSQL shots 表"]
    outline -->|LLM| characters["角色配置<br/>characters/*.yaml"]
    outline -->|LLM| scenes["场景配置<br/>scenes/*.yaml"]

    style outline fill:#1e1b4b,stroke:#7c3aed,color:#c4b5fd
    style storyboard fill:#1e293b,stroke:#334155,color:#e2e8f0
    style characters fill:#1e293b,stroke:#334155,color:#e2e8f0
    style scenes fill:#1e293b,stroke:#334155,color:#e2e8f0
```

| 命令 | 功能 | 依赖 |
|------|------|------|
| `drama generate storyboard 1 -o outline.txt` | 从大纲生成分镜表 | LLM |
| `drama generate characters -d "22岁温柔女生" -d "25岁帅气男生"` | 从描述生成角色 | LLM |
| `drama generate scenes -d "现代简约客厅" -d "繁华商业街"` | 从描述生成场景 | LLM |
| `drama generate all 1 -o outline.txt` | 一键全量生成 | LLM |
| `drama generate bible 1` | 生成角色圣经（character bible） | LLM |

**产出文件：**
- `projects/<项目>/config/characters/*.yaml` — 角色配置（唯一数据源）
- `projects/<项目>/config/scenes/*.yaml` — 场景配置（唯一数据源）
- PostgreSQL 数据库 — 分镜表 / 生成状态（shots / generation_status 表）

---

## 阶段 1 · 准备

> 批量翻译集中完成。运行一次后，生产管线 **零 LLM 调用**。角色圣经（character bible）已移至 `drama generate bible`。

```mermaid
flowchart TB
    subgraph translate["1.1 批量翻译 — LLM"]
        direction TB
        tc["角色翻译<br/>appearance → appearance_en<br/>voice_description → voice_description_en<br/>outfits.*.description → description_en"]
        ts["场景翻译<br/>description → description_en<br/>lighting → lighting_en"]
        tb["分镜翻译<br/>action → action_en<br/>dialogue → dialogue_en"]
    end

    subgraph portraits["1.2 定妆照 — ComfyUI（Web 端单独执行）"]
        direction TB
        pm["主定妆照<br/>特写构图"]
        po["服装参考图<br/>全身构图 × N 套"]
        pm --> po
    end

    subgraph scenes_gen["1.3 场景图 — ComfyUI（Web 端单独执行）"]
        direction TB
        sg["全景参考图<br/>读取 description_en"]
    end

    translate -.->|"可选: --portraits"| portraits
    translate -.->|"可选: --scene-images"| scenes_gen

    yaml1["YAML 文件<br/>reference_images 回写<br/>（唯一数据源）"]
    portraits --> yaml1
    scenes_gen --> yaml1

    style translate fill:#1e293b,stroke:#2563eb,color:#93c5fd
    style portraits fill:#1e293b,stroke:#059669,color:#6ee7b7
    style scenes_gen fill:#1e293b,stroke:#059669,color:#6ee7b7
```

| 命令 | 功能 | 依赖 |
|------|------|------|
| `drama prepare 1` | 批量翻译 | LLM |
| `drama prepare 1 --no-translate` | 无翻译（空操作） | — |
| `drama prepare 1 --force` | 强制覆盖已有翻译 | LLM |

> 定妆照和场景图通过 Web 工作台「📸 定妆照」「🏔️ 场景图」单独执行，支持单角色/单场景按需生成。

### 翻译策略

```mermaid
flowchart LR
    input["中文文本<br/>appearance / description / action ..."] --> check{"文本含<br/>中文字符？"}
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

## 阶段 2 · 生产

> 纯 GPU/本地执行，零 LLM 调用。逐镜头完成 TTS → 首帧 → 视频 → 口型同步。**不含后期合成**（后期由 `drama post` 独立处理）。

```mermaid
flowchart TB
    subgraph produce["drama produce 1 — 镜头生产（不含后期）"]
        direction TB

        subgraph step0["2.0 生成字幕"]
            srt["读取分镜 dialogue<br/>→ episode_01.srt"]
        end

        subgraph loop["2.1 逐镜头循环"]
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
| 2.0 生成字幕 | 0-5% | 读分镜 dialogue → SRT 文件 |
| 2.1 逐镜头循环 | 5-100% | 每个镜头: TTS → 首帧 → 视频 → 口型 |

---

## 阶段 3 · 后期（独立命令）

> `drama post` 单独存在，用于**重做后期**而不重新生成镜头。

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

| 命令 | 功能 |
|------|------|
| `drama post 1` | 后期合成（横屏） |
| `drama post 1 --vertical` | 后期合成 + 横转竖 |

---

## 命令对比

```mermaid
flowchart TB
    subgraph preview["drama preview 1 draft"]
        direction TB
        pr_loop["逐镜头循环<br/>(低质量参数)"]
    end

    subgraph produce["drama produce 1"]
        direction TB
        po_sub["字幕 SRT"]
        po_loop["逐镜头循环"]
        po_sub --> po_loop
    end

    subgraph post["drama post 1"]
        direction TB
        pt_post["后期合成"]
    end

    subgraph all["drama all 1"]
        direction TB
        a_pr["prepare"]
        a_po["produce"]
        a_pt["post"]
        a_pr --> a_po --> a_pt
    end

    style preview fill:#1e293b,stroke:#334155,color:#94a3b8
    style produce fill:#1b3b2e,stroke:#059669,color:#6ee7b7
    style post fill:#1e293b,stroke:#d97706,color:#fcd34d
    style all fill:#1b2e4b,stroke:#2563eb,color:#93c5fd
```

| 命令 | 字幕 | 镜头循环 | 后期合成 | 用途 |
|------|:----:|:--------:|:--------:|------|
| `drama preview 1 draft` | ❌ | ✅ 低质量 | ❌ | 快速预览效果 |
| `drama produce 1` | ✅ | ✅ 全质量 | ❌ | **镜头生产**（不含后期） |
| `drama post 1` | ❌ | ❌ | ✅ | 重做后期（换配乐/加竖屏） |
| `drama all 1` | ✅ | ✅ | ✅ | 一键全流程（prepare → produce → post） |

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
        s0["阶段0: LLM 生成"]
        s1t["阶段1.1: LLM 翻译"]
        s1p["阶段1.2: ComfyUI 定妆照"]
        s1s["阶段1.3: ComfyUI 场景图"]
        s2t["阶段2: TTS"]
        s2f["阶段2: ComfyUI 首帧"]
        s2v["阶段2: ComfyUI 视频"]
        s2l["阶段2: LipSync"]
        s3["阶段3: FFmpeg 后期"]
    end

    s0 -->|"生成"| yaml_c & yaml_s & db_sb
    s1t -->|"翻译写入 *_en"| yaml_c & yaml_s & db_sb
    s1p -->|"生成图片"| assets_c
    s1s -->|"生成图片"| assets_s
    yaml_c & yaml_s -->|"读取 *_en"| s2f & s2s
    db_sb -->|"读取 dialogue"| s2t
    s2t -->|"audio.wav"| output
    s2f -->|"frame.png"| output
    s2v -->|"video.mp4"| output
    s2l -->|"synced.mp4"| output
    output -->|"拼接"| s3
    s3 -->|"final.mp4"| final

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
    llm -.->|"阶段0+1"| celery
    seko -.->|"策划案导入"| celery
    ffmpeg -.->|"阶段3"| celery

    style required fill:#1b3b2e,stroke:#059669,color:#6ee7b7
    style production fill:#1b2e4b,stroke:#2563eb,color:#93c5fd
    style optional fill:#1e293b,stroke:#334155,color:#94a3b8
```

---

## 快速参考

```bash
# 首次使用
drama generate all 1 -o outline.txt    # 从大纲生成全部素材
drama generate bible 1                 # 生成角色圣经（character bible）
drama prepare 1                        # 准备阶段（批量翻译）

# 日常生产
drama produce 1                        # 镜头生产（TTS → 首帧 → 视频 → 口型）
drama produce 1 --force                # 强制重新生成
drama post 1                           # 后期合成（横屏）
drama post 1 --vertical                # 后期合成 + 横转竖

# 完整流程
drama all 1                            # 一键: prepare → produce → post

# 单独操作
drama preview 1 draft                  # 快速预览
drama portraits                        # 只生成定妆照

# 服务管理
drama serve                            # 启动 Web 工作台
drama worker                           # 启动 Celery Worker
drama status                           # 查看服务状态
```
