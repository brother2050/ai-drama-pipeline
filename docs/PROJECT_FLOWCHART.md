# 🎬 AI 短剧管线 v2 — 完整流程图

## 一、系统架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        用户入口                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │  CLI (drama)  │  │  Web 工作台   │  │  Celery Worker│              │
│  │  serve/worker │  │  FastAPI SPA │  │  异步任务执行  │              │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘              │
│         │                  │                  │                      │
│         └──────────────────┼──────────────────┘                      │
│                            ▼                                         │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    共享基础设施                                │    │
│  │  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐   │    │
│  │  │ Config   │ │ DB Pool  │ │ Redis    │ │ ModelRegistry │   │    │
│  │  │ YAML热重载│ │PostgreSQL│ │ Celery   │ │ YAML驱动后端  │   │    │
│  │  └─────────┘ └──────────┘ └──────────┘ └───────────────┘   │    │
│  │  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐   │    │
│  │  │ Hooks   │ │ WatchDog │ │ FileWatch│ │ DI Container  │   │    │
│  │  │ 清理钩子 │ │ 超时监控  │ │ YAML监控 │ │ 后端按需创建   │   │    │
│  │  └─────────┘ └──────────┘ └──────────┘ └───────────────┘   │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 二、核心数据流 — 从剧本到成片

```
用户输入大纲
    │
    ▼
┌───────────────────────────────────────────────────────────────┐
│ 阶段 1: AI 分镜生成                                            │
│ task: pipeline_ai_storyboard                                  │
│                                                               │
│ 输入: outline(大纲文本), episode(集数), duration(目标时长)       │
│ 处理: LLM 生成 shot_id/scene_id/characters/action/dialogue/    │
│       camera/shot_type/duration/emotion/outfit                 │
│ 输出: shots[] → 写入 DB (shots表)                              │
│ 副作用: 报告 missing_characters / missing_scenes               │
│ ──────────────────────────────────────────────────────────────│
│ 截断保护:                                                     │
│   1. 预期时长÷8 = expected_min                                │
│   2. 预期时长÷3 = expected_max                                │
│   3. 不足时自动续生成（LLM 从 last_id+1 继续）                  │
│   4. 超限时硬截断（保留前 expected_max 个）                     │
└───────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────┐
│ 阶段 2: AI 实体生成                                            │
│ task: pipeline_ai_entities                                    │
│                                                               │
│ 输入: 从 DB 读取分镜 → 提取引用的 char_ids / scene_ids          │
│ 处理:                                                         │
│   1. 场景去重（LLM 审查 scene_id，合并同物理位置）              │
│   2. 过滤已有实体（YAML 文件系统）                              │
│   3. LLM 批量生成缺失的角色/场景（一次生成中英双语）            │
│   4. validate_character/validate_scene 校验+补全字段           │
│ 输出: 角色YAML (config/characters/*.yaml)                      │
│       场景YAML (config/scenes/*.yaml)                          │
│ ──────────────────────────────────────────────────────────────│
│ 角色YAML 结构:                                                 │
│   character:                                                  │
│     id, name, gender, age, appearance(中文)                    │
│     appearance_prompt_en(英文绘图prompt)                       │
│     body_features(身体特征)                                    │
│     outfits: {default: {description, description_en}}          │
│     bible: {core_traits, speech_patterns, voice_description,  │
│             emotional_range, body_language, habits, taboos}    │
│     bible_en: {同上全部字段_en后缀}                             │
│     reference_images: []                                       │
│                                                               │
│ 场景YAML 结构:                                                 │
│   scene:                                                      │
│     id, name, description(中文), description_en(英文)          │
│     lighting(中文), lighting_en(英文)                          │
│     reference_images: []                                       │
└───────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────┐
│ 阶段 3: 准备阶段（翻译兜底 + 视角prompt）                      │
│ task: pipeline_ai_prepare                                     │
│                                                               │
│ 输入: 扫描所有角色/场景/分镜的缺失英文字段                      │
│ 处理:                                                         │
│   1. _collect_missing_texts: 收集缺失英文的文本+元信息          │
│   2. _batch_translate_texts: UID标记批量翻译（15条/批）        │
│   3. _validate_and_retry: 质量校验→批量重试→逐条兜底           │
│   4. _writeback_translations: 回写YAML+DB                     │
│   5. _generate_view_prompts: 角色5视图prompt生成               │
│ 输出: 英文字段补全 + appearance_prompt_en                      │
│ ──────────────────────────────────────────────────────────────│
│ 翻译质量检查:                                                  │
│   - 空翻译 → 不合格                                           │
│   - 中文源→英文目标仍含中文 → 不合格                           │
│   - 源>10字符且目标<3词 → 不合格                               │
│   - 不合格>30% → 跳过重试（LLM服务异常）                       │
│   - 批量重试 → 逐条兜底                                       │
│                                                               │
│ 视角prompt (5视图):                                            │
│   front / left_side / back / three_quarter / right_side        │
│   shot_type映射:                                              │
│     特写/近景/中景/全身/过肩 → front                           │
│     侧面特写 → left_side                                      │
│     背面特写 → back                                            │
│     3/4侧/三人全景 → three_quarter                             │
└───────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────┐
│ 阶段 4: 定妆照生成                                             │
│ task: pipeline_portraits / pipeline_portrait_single            │
│                                                               │
│ 输入: 角色YAML (appearance_prompt_en + outfits)                │
│ 处理:                                                         │
│   1. WorkflowBuilder 构建 ComfyUI 首帧工作流                   │
│   2. 调用 ComfyUI /object_info 获取可用节点                      │
│   3. 注入 IP-Adapter/PuLID 面部一致性（按节点可用性自动跳过）     │
│      - 若 required_comfyui_nodes 缺失 → Warning + 跳过，不中断  │
│   4. 注入角色 LoRA（如有训练）                                  │
│   5. 注入全局 LoRA（如 ACE++ Portrait）                        │
│   6. ComfyUI 生成 → cover.png                                 │
│   7. 各服装 outfit_*.png                                       │
│ 输出: assets/characters/{id}/cover.png                         │
│       assets/characters/{id}/default/outfit_*.png              │
│ ──────────────────────────────────────────────────────────────│
│ 一致性方案 (按 image_backend):                                 │
│   flux  → PuLID-Flux (面部ID注入)                              │
│   sd15  → IP-Adapter Plus (面部特征注入)                       │
│   cosmos → 无一致性方案（仅LoRA+seed）                         │
│   auto  → 根据 image_backend 自动选择                          │
│ ──────────────────────────────────────────────────────────────│
│ 节点可用性校验 (启动时):                                        │
│   检查 required_comfyui_nodes → 缺失则跳过对应方案 (WARNING)    │
└───────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────┐
│ 阶段 5: 场景图生成                                             │
│ task: pipeline_scene_images / pipeline_scene_image_single      │
│                                                               │
│ 输入: 场景YAML (description_en)                                │
│ 处理: WorkflowBuilder 构建工作流 → ComfyUI 生成                 │
│ 输出: assets/scenes/{id}/cover.png                             │
│ 副作用: 更新场景YAML reference_images                          │
└───────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────┐
│ 阶段 6: 镜头生产（逐镜头串行/并发）                            │
│ task: pipeline_produce → pipeline_shot (×N镜头)                │
│                                                               │
│ 每个镜头执行 4 步（级联跳过）:                                  │
│                                                               │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ Step 1: TTS (pipeline_step_tts)                          │   │
│ │                                                         │   │
│ │ 输入: shot.dialogue (台词文本)                            │   │
│ │ 处理:                                                   │   │
│ │   1. parse_dialogue → 解析"角色名：台词"格式             │   │
│ │   2. _resolve_char → 按name/id查找角色数据               │   │
│ │   3. _build_voice_config → 构建voice_config             │   │
│ │      (reference_audio + voice_description + 后端专属参数)│   │
│ │   4. TTS后端.synthesize → 生成WAV                       │   │
│ │   5. 多条台词: 逐条合成→concat_wav拼接                   │   │
│ │ 输出: output/e01/s001/audio.wav                          │   │
│ │ 并发组: tts (2 slots)                                    │   │
│ │ 看门狗: 300s 超时                                        │   │
│ └─────────────────────────────────────────────────────────┘   │
│                    │                                          │
│                    ▼                                          │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ Step 2: 首帧 (pipeline_step_first_frame)                 │   │
│ │                                                         │   │
│ │ 输入: shot + 角色appearance_prompt_en + 场景description_en│   │
│ │ 处理:                                                   │   │
│ │   1. _resolve_shot_context:                             │   │
│ │      - 角色描述 (get_view_appearance + outfit描述注入)   │   │
│ │      - 场景描述 (description_en)                        │   │
│ │      - 多人提示 (MultiCharacterHandler)                  │   │
│ │      - 服装自动匹配 (outfit为空时回退default)            │   │
│ │   2. WorkflowBuilder.build_first_frame:                  │   │
│ │      - 加载工作流模板 (workflows/*.json)                 │   │
│ │      - GPU参数注入 (分辨率/步数/采样器)                  │   │
│ │      - Prompt注入 (positive/negative)                    │   │
│ │      - 一致性方案注入 (IP-Adapter/PuLID/LoRA)           │   │
│ │        (自动节点检测: 缺失则 WARNING 跳过，不中断管线)     │   │
│ │      - Seed随机化                                        │   │
│ │   3. 并行上传参考图到ComfyUI                             │   │
│ │   4. comfyui_generate → frame.png                       │   │
│ │ 输出: output/e01/s001/frame.png                          │   │
│ │ 并发组: comfyui (1 slot)                                 │   │
│ │ 看门狗: 300s 超时                                        │   │
│ └─────────────────────────────────────────────────────────┘   │
│                    │                                          │
│                    ▼                                          │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ Step 3: 视频 (pipeline_step_video)                       │   │
│ │                                                         │   │
│ │ 输入: frame.png + shot                                   │   │
│ │ 处理:                                                   │   │
│ │   1. 上传首帧到ComfyUI                                  │   │
│ │   2. WorkflowBuilder.build_video:                        │   │
│ │      - 加载视频工作流模板                                │   │
│ │      - 注入视频prompt (appearance + scene + outfit)      │   │
│ │      - 注入帧数 (= duration × fps)                      │   │
│ │   3. comfyui_generate → video.mp4                       │   │
│ │ 输出: output/e01/s001/video.mp4                          │   │
│ │ 并发组: comfyui (1 slot)                                 │   │
│ │ 看门狗: 600s 超时                                        │   │
│ └─────────────────────────────────────────────────────────┘   │
│                    │                                          │
│                    ▼                                          │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ Step 4: 口型同步 (pipeline_step_lipsync)                 │   │
│ │                                                         │   │
│ │ 输入: video.mp4 + audio.wav                              │   │
│ │ 处理: Lipsync后端.synthesize → synced.mp4                │   │
│ │ 输出: output/e01/s001/synced.mp4                         │   │
│ │ 并发组: lipsync (1 slot)                                 │   │
│ │ 看门狗: 300s 超时                                        │   │
│ └─────────────────────────────────────────────────────────┘   │
│                                                               │
│ 依赖关系:                                                      │
│   TTS → 独立                                                   │
│   首帧 → 独立                                                  │
│   视频 → 依赖首帧 (frame.png 必须存在)                         │
│   口型 → 依赖视频 + TTS                                        │
│                                                               │
│ 重试: 失败镜头自动重试一次 (force=True)                         │
│ 并发: run_staggered_sync (max_concurrent=2, stagger=3s)        │
└───────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────┐
│ 阶段 7: 后期合成                                               │
│ task: pipeline_post                                           │
│                                                               │
│ 步骤:                                                         │
│   1. _collect_videos: 收集 synced.mp4 > video.mp4             │
│   2. 探测各镜头实际时长 (ffprobe)                              │
│   3. generate_srt: 生成SRT字幕 (按实际视频时长对齐)            │
│   4. _concat_videos: 拼接 (crossfade转场 → 失败回退简单拼接)   │
│   5. 转场回退后重新生成SRT (无转场时序不同)                    │
│   6. _add_subtitles: 烧录字幕 (失败跳过)                      │
│   7. _generate_and_mix_bgm: 自动生成配乐+混合 (失败跳过)       │
│   8. _to_vertical: 横转竖 (可选，失败跳过)                     │
│   9. _rename_final: 重命名为 final.mp4                        │
│  10. _cleanup_and_update_db: 清理中间文件                      │
│                                                               │
│ 输出: output/e01/episode_01_final.mp4                          │
│       output/e01/episode_01.srt                                │
│ ──────────────────────────────────────────────────────────────│
│ 配乐生成:                                                      │
│   - 从分镜提取情绪分布 → 取众数作为mood                        │
│   - 总时长 = 所有镜头视频实际时长之和                           │
│   - MusicGenerator.generate → bgm.wav                         │
│   - FFmpeg.mix_audio (video_vol=1.0, audio_vol=0.15)          │
└───────────────────────────────────────────────────────────────┘
```

---

## 三、一键全流程 (run_all_task)

```
用户点击「一键全流程」
    │
    ▼
pipeline_run_all(config_path, episode, vertical, force)
    │
    ├── 前置检查: 分镜是否存在? → 否 → STATUS_ERROR
    │
    ├── ① entities: ai_entities_task
    │   └── 生成缺失的角色/场景 YAML
    │
    ├── ② prepare: ai_prepare_task
    │   └── 翻译缺失的英文字段 + 视角prompt
    │
    ├── ③ portraits: portraits_task
    │   └── 生成定妆照 (ComfyUI)
    │
    ├── ④ produce: produce_task
    │   └── 逐镜头执行 TTS→首帧→视频→口型
    │
    └── ⑤ post: post_task
        └── 拼接→字幕→配乐→(横转竖)→final.mp4

    任一阶段 STATUS_ERROR → 全流程中止，返回失败阶段+原因
    任一阶段 STATUS_SKIPPED → 记录警告，继续下一阶段
    produce 阶段镜头级错误 → 不阻断全流程，记录 _has_errors
```

---

## 四、数据库 Schema

```
shots 表（分镜数据，唯一数据源）
┌────────────────────────────────────────────────────────┐
│ project    TEXT NOT NULL DEFAULT 'default'              │
│ episode    INTEGER NOT NULL                             │
│ shot_id    TEXT NOT NULL                                │
│ scene_id   TEXT DEFAULT ''                              │
│ characters TEXT DEFAULT ''   (如 "林夏+顾辰")           │
│ action     TEXT DEFAULT ''   (中文画面描述)              │
│ dialogue   TEXT DEFAULT ''   (中文台词)                  │
│ action_en  TEXT DEFAULT ''   (英文画面描述)              │
│ dialogue_en TEXT DEFAULT ''  (英文台词)                  │
│ camera     TEXT DEFAULT ''   (运镜: 固定/缓慢推近/...)   │
│ shot_type  TEXT DEFAULT ''   (景别: 特写/近景/中景/...)  │
│ duration   REAL DEFAULT 4    CHECK [2, 8]               │
│ emotion    TEXT DEFAULT 'neutral'                        │
│ outfit     TEXT DEFAULT 'default'                        │
│ PRIMARY KEY (project, episode, shot_id)                  │
└────────────────────────────────────────────────────────┘

generation_status 表（生成状态跟踪）
┌────────────────────────────────────────────────────────┐
│ project    TEXT NOT NULL DEFAULT 'default'              │
│ episode    INTEGER NOT NULL                             │
│ shot_id    TEXT NOT NULL                                │
│ stage      TEXT NOT NULL  (tts/first_frame/video/lipsync)│
│ status     TEXT DEFAULT 'pending' CHECK [pending,       │
│            running, done, error, skipped]               │
│ path       TEXT DEFAULT ''   (输出文件路径)              │
│ error      TEXT DEFAULT ''   (错误信息)                  │
│ elapsed    REAL DEFAULT 0    (耗时秒数)                  │
│ UNIQUE(project, episode, shot_id, stage)                 │
└────────────────────────────────────────────────────────┘

comfyui_assets 表（ComfyUI 资产跟踪）
┌────────────────────────────────────────────────────────┐
│ project    TEXT NOT NULL DEFAULT 'default'              │
│ server_url TEXT NOT NULL                                │
│ asset_type TEXT NOT NULL CHECK [image, lora]            │
│ filename   TEXT NOT NULL                                │
│ UNIQUE(project, server_url, asset_type, filename)       │
└────────────────────────────────────────────────────────┘
```

---

## 五、文件系统结构

```
ai-drama-pipeline/
├── config/
│   ├── system.yaml              # 系统全局配置
│   ├── models_registry.yaml     # 后端元数据注册表（唯一真相源）
│   └── prompt_templates.yaml    # LLM prompt 模板
├── projects/
│   ├── .active                  # 当前活动项目指针
│   └── default/
│       ├── config/
│       │   ├── project.yaml     # 项目配置
│       │   ├── characters/
│       │   │   ├── 林夏.yaml
│       │   │   └── 顾辰.yaml
│       │   └── scenes/
│       │       ├── 客厅.yaml
│       │       └── 街道.yaml
│       ├── assets/
│       │   ├── characters/
│       │   │   └── 林夏/
│       │   │       ├── cover.png
│       │   │       ├── default/
│       │   │       │   └── outfit_*.png
│       │   │       └── lora/
│       │   └── scenes/
│       │       └── 客厅/
│       │           └── cover.png
│       └── output/
│           └── e01/
│               ├── s001/
│               │   ├── audio.wav      # TTS 输出
│               │   ├── frame.png      # 首帧
│               │   ├── video.mp4      # 视频
│               │   └── synced.mp4     # 口型同步
│               ├── episode_01.srt      # 字幕
│               └── episode_01_final.mp4 # 成片
├── shared_assets/
│   └── voices/                  # 声线库
├── workflows/                   # ComfyUI 工作流模板
│   ├── flux_first_frame.json
│   ├── cosmos_first_frame.json
│   ├── sd15_first_frame.json
│   ├── animatediff_video.json
│   └── cosmos_video.json
├── api/backends/                # 后端实现
│   ├── tts/                     # TTS 后端 (6个)
│   ├── image/                   # 图像后端 (ComfyUI)
│   ├── video/                   # 视频后端 (AnimateDiff)
│   ├── lipsync/                 # 口型同步 (2个)
│   ├── llm/                     # LLM 后端 (OpenAI-compat)
│   ├── music/                   # 配乐 (MusicGen/模板)
│   ├── training/                # LoRA 训练
│   └── seko/                    # Seko 策划案
├── engines/                     # 核心业务逻辑
├── pipeline/                    # Celery 任务
├── post/                        # 后期合成
├── web/                         # Web 工作台
└── scripts/                     # 工具脚本
```

---

## 六、后端注册表 (models_registry.yaml)

```
服务类型          后端名              优先级  说明
─────────────────────────────────────────────────────
TTS
  mimo-voicedesign               10    小米MiMo语音设计（默认）
  mimo-voiceclone                20    小米MiMo声音克隆
  gpt_sovits                     30    GPT-SoVITS（本地部署）
  cosyvoice                      40    CosyVoice（本地部署）
  fish_speech                    50    Fish Speech（本地部署）
  chattts                        60    ChatTTS（本地部署）

图像
  flux                           10    Flux（≥32GB显存）
  flux-fp8                       20    Flux FP8（~16GB显存）
  sd15                           30    SD1.5（≥6GB显存）
  cosmos                         40    Cosmos（≥12GB显存，默认推荐）
  hidream                        50    HiDream（≥24GB显存）

视频
  animatediff                    10    AnimateDiff（SD1.5）
  cosmos-video                   20    Cosmos Video（默认推荐）
  cogvideox                      30    CogVideoX（≥24GB显存）

口型同步
  musetalk                       10    MuseTalk（默认）
  wav2lip                        20    Wav2Lip

LLM
  openai                         10    OpenAI兼容API（默认）
  ollama                         50    Ollama本地

配乐
  template                       10    模板配乐（默认）
  musicgen                       20    MusicGen AI配乐

训练
  ai_toolkit                     10    AI Toolkit LoRA训练

策划案
  seko                           10    Seko 影视策划案
```

---

## 七、DI 容器 + 自注册

```
api/__init__.py
    │
    ├── _ensure_registered() → 遍历所有 backends/*.py
    │   每个后端文件底部调用 registry.register(BackendMeta(...))
    │
    └── Container(config)
        │
        ├── get("tts") → _resolve("tts")
        │   ├── 1. config.models.tts_backend → "mimo-voicedesign"
        │   ├── 2. registry.get("tts", "mimo-voicedesign")
        │   └── 3. factory(config) → TTS实例
        │
        ├── get_with_fallback("tts") → 主后端不可用时自动fallback
        │   └── 遍历同类型其他后端（按priority排序）
        │
        └── reload(new_config) → 检测配置变化，增量重建
```

---

## 八、Web API 路由表

```
/api/
├── /episodes                     GET    集数列表
├── /episodes/summary             GET    集数摘要（镜头数/时长/进度）
├── /episodes/{ep}                DELETE 删除集
├── /episodes/{ep}/clear          POST   清理集输出
│
├── /storyboard/{ep}              GET    获取分镜表
├── /storyboard/{ep}              POST   保存分镜表
├── /storyboard/{ep}/batch-delete POST   批量删除镜头
│
├── /pipeline/run                 POST   执行管线 (preview/prepare/produce/post/run_all)
├── /pipeline/status/{ep}         GET    管线状态
│
├── /prepare                      POST   准备阶段
│
├── /llm/storyboard               POST   AI生成分镜
├── /llm/entities                 POST   AI生成实体
├── /llm/characters               POST   AI生成角色
├── /llm/scenes                   POST   AI生成场景
├── /llm/chat-edit                POST   对话式编辑分镜
│
├── /shots/{ep}/{sid}/resources   GET    镜头资源列表
├── /files/{ep}/{sid}/{file}      GET    镜头文件下载
├── /project-file/{path}          GET    项目文件下载
│
├── /characters                   CRUD   角色管理
├── /characters/{id}/portrait     POST   生成定妆照
├── /characters/{id}/outfits      POST   生成服装图
│
├── /scenes                       CRUD   场景管理
├── /scenes/{id}/image            POST   生成场景图
│
├── /assets/...                   各类资产上传/下载/管理
│
├── /voices/...                   声线库管理
│
├── /projects                     GET    项目列表
├── /projects/new                 POST   创建项目
├── /projects/switch              POST   切换项目
├── /projects/{name}              DELETE 删除项目
│
├── /import/...                   导入（JSON/Seko/CSV）
├── /training/...                 LoRA训练
├── /seko/...                     Seko策划案
│
├── /system/status                GET    系统状态
├── /system/config                GET/PUT 系统配置
├── /system/tools                 GET    工具状态
└── /tasks/{id}                   GET    任务状态轮询
```

---

## 九、Celery 任务依赖图

```
pipeline_run_all
    │
    ├── pipeline_ai_entities
    │   └── (LLM: 从分镜提取→生成缺失角色/场景)
    │
    ├── pipeline_ai_prepare
    │   └── (LLM: 批量翻译 + 视角prompt)
    │
    ├── pipeline_portraits
    │   └── pipeline_portrait_single × N角色
    │       └── (ComfyUI: 定妆照生成)
    │
    ├── pipeline_produce
    │   └── pipeline_shot × N镜头
    │       ├── pipeline_step_tts        → audio.wav
    │       ├── pipeline_step_first_frame → frame.png
    │       ├── pipeline_step_video      → video.mp4
    │       └── pipeline_step_lipsync    → synced.mp4
    │
    └── pipeline_post
        └── (ffmpeg: 拼接→字幕→配乐→final.mp4)

独立任务:
    pipeline_ai_storyboard    (LLM: 大纲→分镜)
    pipeline_ai_characters    (LLM: 描述→角色)
    pipeline_ai_scenes        (LLM: 描述→场景)
    pipeline_ai_chat_edit     (LLM: 自然语言→修改分镜)
    pipeline_scene_images     (ComfyUI: 场景图)
    pipeline_tts_single       (TTS: 单条试听)
    pipeline_music            (MusicGen: 配乐)
    pipeline_subtitle         (SRT: 字幕生成)
    pipeline_train_lora       (AI Toolkit: LoRA训练)
    pipeline_import_json      (JSON导入)
    pipeline_seko_import      (Seko策划案导入)
```

---

## 十、配置热重载链路

```
YAML 文件变化
    │
    ▼
FileWatcher (watchdog)
    │
    ├── 1. invalidate_config_cache()     → Config._cache 清空
    ├── 2. run_hooks("cache_invalidate") → Pipeline ctx_cache 清空
    │                                     → TTS char_cache 清空
    └── 3. ModelRegistry._instance = None → 下次访问重新加载

下次访问时:
    Config.get() → _check_reload() → 检测mtime变化 → _do_reload()
    Container.reload(new_config) → 检测后端配置变化 → 增量重建
```

---

## 十一、错误处理策略

```
错误类型              处理方式
──────────────────────────────────────────────
ComfyUI 超时          WatchDog 300s/600s → 标记 TIMEOUT
ComfyUI 生成失败      重试1次 (force=True)
TTS 合成失败          safe_run 重试2次 (base_delay=1s)
LLM 返回格式错误      parse_llm_json 容错解析
LLM 翻译质量差        三层重试: 批量→逐条→跳过
LLM 翻译>30%失败      跳过重试（服务异常）
视频拼接失败          回退简单拼接（无转场）
字幕添加失败          跳过（不阻断）
配乐生成失败          跳过（不阻断）
横转竖失败            跳过（不阻断）
角色参考图上传失败    阻断（raise RuntimeError）
一致性插件节点缺失     跳过，记录 WARNING（/object_info 自动检测）
场景图上传失败        警告（不阻断）
DB 连接失败           降级（文件系统回退）
Redis 不可用          CLI 自动尝试启动
```
