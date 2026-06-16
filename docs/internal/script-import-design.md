# 剧本导入功能 — 设计文档

> 在 DeepSeek / Kimi / 豆包 / MiMo Pro 等 AI 对话平台提取剧本为 JSON，上传导入，一键生成可直接运行的短剧项目。

---

## 一、目标

用户在 AI 对话平台（DeepSeek / Kimi / 豆包 / MiMo Pro 等）将剧本粘贴给 AI，AI 输出结构化 JSON，用户复制 JSON 后上传到本系统导入。

**核心原则：格式交给三方平台，本地只管接收。**

- 角色/场景/分镜的提取由三方平台完成，用户交互式调整后复制 JSON
- 本地只负责：**严格校验 JSON Schema → 写入项目目录（YAML 为唯一数据源）**
- 校验失败**立即报错**，不进入半成品状态（开始出错 > 运行时出错）

### ⚠ 核心问题：LLM 输出截断

30 分钟完整剧本约 200 个镜头，JSON 数据量约 40-60K tokens，**远超主流 LLM 单次输出上限**（4K-8K tokens）。

**解决方案：分批生成 + 追加导入**

| 阶段 | 内容 | 预估 tokens |
|------|------|------------|
| 第 1 轮 | characters + scenes + shots 001-050 | ~8K ✅ |
| 第 2 轮 | shots 051-100 | ~5K ✅ |
| 第 3 轮 | shots 101-150 | ~5K ✅ |
| 第 4 轮 | shots 151-200 | ~5K ✅ |

每轮输出独立 JSON，分别导入。第 1 轮全量创建项目，后续轮次追加 shots。

---

## 二、导入路径

| 路径 | 格式 | 说明 |
|------|------|------|
| **JSON 导入**（唯一推荐） | `.json` | 角色 + 场景 + 分镜一次性导入 |
| **JSON 追加导入** | `.json` + `--append` | 向已有项目追加分镜（解决 LLM 截断） |
| **Seko 导入**（已有） | API | 从 seko.sensetime.com 策划案导入 |

**不支持 CSV 导入**。原因：

1. 分镜字段多（16+ 列），人工填写极易出错
2. 角色/场景需要单独导入，CSV 无法承载完整项目
3. 需要手动匹配角色/场景 ID，出错率高
4. 分镜表存储已迁移到 PostgreSQL，CSV 仅作为导出格式

---

## 三、JSON Schema 定义

### 3.1 顶层结构

```json
{
  "project_name": "都市恋歌",
  "style": "cinematic",
  "genre": "urban",
  "synopsis": "一个关于都市爱情的故事...",
  "characters": [...],
  "scenes": [...],
  "shots": [...]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `project_name` | string | ✅ | 项目名，1-100 字符，允许中英文/数字/下划线/连字符 |
| `style` | enum | | 视觉风格，默认 `cinematic` |
| `genre` | enum | | 题材类型，默认 `urban` |
| `synopsis` | string | | 剧情简介，≤500 字符 |
| `characters` | array | | 角色列表（可空，后续单独添加） |
| `scenes` | array | | 场景列表（可空，后续单独添加） |
| `shots` | array | | 分镜列表（可空，后续单独添加） |
| `append` | boolean | | 追加模式，默认 `false`。设为 `true` 时向已有项目追加 shots |

**注意**：`characters` 和 `scenes` 可以为空数组，但 `shots` 中引用的 `characters`/`scene` ID 必须在对应数组中存在，否则校验失败。

### 3.2 角色 (Character)

```json
{
  "id": "linxia",
  "name": "林夏",
  "gender": "female",
  "age": "22",
  "appearance": "22岁，长发及腰，温柔的眼神，身材娇小，皮肤白皙",
  "outfits": {
    "default": {
      "description": "白色连衣裙，简约优雅，腰间系一条细腰带"
    },
    "casual": {
      "description": "浅蓝色牛仔裤配白色T恤，休闲随意"
    }
  }
}
```

| 字段 | 类型 | 必填 | 约束 | 说明 |
|------|------|:----:|------|------|
| `id` | string | ✅ | `^[a-zA-Z0-9_-]+$`，1-50 字符 | 角色唯一标识，英文/数字/下划线/连字符 |
| `name` | string | ✅ | 1-100 字符 | 角色名称（中英文均可） |
| `gender` | string | | ≤10 字符 | 性别 |
| `age` | string | | ≤10 字符 | 年龄或年龄段描述 |
| `appearance` | string | ✅ | 10-2000 字符 | 外貌描述（中文，用于 LLM 翻译为英文 prompt） |
| `outfits` | object | | key: `^[a-zA-Z0-9_]+$` | 服装字典，至少需要 `default` |
| `outfits.*.description` | string | | 1-500 字符 | 服装描述（中文） |
| `outfits.*.description_en` | string | | ≤1000 字符 | 英文服装描述（可选，提供则跳过翻译） |
| `appearance_prompt_en` | string | | ≤4000 字符 | 英文外貌 prompt（可选，提供则跳过翻译） |
| `body_features` | string | | ≤2000 字符 | 身体特征：伤疤/纹身/胎记等（可选） |

### 3.3 场景 (Scene)

```json
{
  "id": "living_room",
  "name": "客厅",
  "description": "现代简约客厅，落地窗暖光，木质地板，米色沙发，墙上挂着几幅画",
  "lighting": "自然光从落地窗洒入，暖色调，黄昏时分有金色余晖"
}
```

| 字段 | 类型 | 必填 | 约束 | 说明 |
|------|------|:----:|------|------|
| `id` | string | ✅ | `^[a-zA-Z0-9_-]+$`，1-50 字符 | 场景唯一标识 |
| `name` | string | ✅ | 1-100 字符 | 场景名称 |
| `description` | string | ✅ | 10-2000 字符 | 场景描述（中文，用于 LLM 翻译） |
| `lighting` | string | | ≤200 字符 | 光照描述 |
| `description_en` | string | | ≤4000 字符 | 英文场景描述（可选，提供则跳过翻译） |
| `lighting_en` | string | | ≤400 字符 | 英文光照描述（可选） |

### 3.4 分镜 (Shot)

```json
{
  "episode": 1,
  "shot_id": "001",
  "scene_id": "living_room",
  "characters": "linxia",
  "action": "林夏坐在沙发上翻着手机，眉头微皱",
  "dialogue": "他怎么还不回消息...",
  "camera": "固定",
  "shot_type": "近景",
  "duration": 4,
  "emotion": "worried",
  "outfit": "default",
  "language": "zh"
}
```

| 字段 | 类型 | 必填 | 约束 | 说明 |
|------|------|:----:|------|------|
| `episode` | int | | 默认 `1` | 集数 |
| `shot_id` | string | ✅ | `^[a-zA-Z0-9_-]+$`，1-20 字符 | 镜头 ID，推荐三位数字 `001` 起递增 |
| `scene_id` | string | ✅ | 必须匹配 `scenes[].id` | 场景 ID |
| `characters` | string | | 多人用 `+` 连接，必须匹配 `characters[].id` | 角色 ID |
| `action` | string | ✅ | 5-500 字符 | 动作/画面描述（中文） |
| `dialogue` | string | | ≤500 字符，无台词填 `"......"` | 台词（中文） |
| `camera` | string | | 见下方枚举 | 运镜方式 |
| `shot_type` | string | | 见下方枚举 | 景别 |
| `duration` | int | | 2-8 | 时长（秒） |
| `emotion` | string | | 见下方枚举 | 角色情绪 |
| `outfit` | string | | 必须匹配角色的 `outfits` key | 服装标签 |
| `language` | string | | `zh` / `en` | 台词语言，默认 `zh` |
| `action_en` | string | | ≤2000 字符 | 英文画面描述（可选，提供则跳过翻译） |
| `dialogue_en` | string | | ≤1000 字符 | 英文台词（可选） |

### 3.5 枚举值（严格匹配项目）

**景别 `shot_type`**：

| 值 | 说明 |
|------|------|
| `特写` | 面部/物体细节 |
| `近景` | 胸部以上 |
| `中景` | 腰部以上 |
| `过肩` | 过肩镜头（对话场景） |
| `全身` | 完整人物 |
| `全景` | 人物+环境 |
| `远景` | 环境为主，人物很小 |

**运镜 `camera`**：

| 值 | 说明 |
|------|------|
| `固定` | 三脚架固定机位 |
| `缓慢推近` | 慢速推进，营造压迫感/聚焦 |
| `跟随平移` | 跟随角色移动 |
| `手持晃动` | 手持拍摄，纪实感 |
| `环绕` | 环绕角色拍摄 |
| `俯视` | 高角度俯拍 |
| `仰视` | 低角度仰拍 |

**情绪 `emotion`**：

| 值 | 说明 |
|------|------|
| `happy` | 开心 |
| `sad` | 悲伤 |
| `worried` | 担忧 |
| `surprised` | 惊讶 |
| `angry` | 愤怒 |
| `calm` | 平静 |
| `neutral` | 中性/无明显情绪 |

**视觉风格 `style`**：

| 值 | 说明 |
|------|------|
| `cinematic` | 电影质感 — 专业打光、宽银幕构图、电影色调 |
| `anime` | 动漫风格 — 日系画风、鲜艳色彩、夸张表情 |
| `realistic` | 写实风格 — 真实光影、自然色彩、纪录片质感 |
| `noir` | 黑色电影 — 暗调光影、高对比度、冷峻氛围 |
| `fantasy` | 奇幻风格 — 魔法元素、华丽特效、异世界感 |
| `vintage` | 复古风格 — 胶片质感、暖色调、怀旧氛围 |
| `minimalist` | 极简风格 — 干净画面、留白构图、淡雅色调 |
| `cyberpunk` | 赛博朋克 — 霓虹灯光、科技感、暗色调 |
| `watercolor` | 水彩风格 — 柔和晕染、通透色彩、手绘质感 |
| `ink_wash` | 水墨风格 — 东方意境、留白泼墨、古典韵味 |
| `comic` | 漫画风格 — 粗线条、网点纸、分镜感 |
| `oil_painting` | 油画风格 — 厚涂笔触、浓郁色彩、古典构图 |
| `steampunk` | 蒸汽朋克 — 齿轮机械、铜色金属、维多利亚风 |
| `pop_art` | 波普艺术 — 高饱和、拼贴感、商业视觉 |
| `glitch` | 故障艺术 — 数字失真、RGB偏移、科技废墟感 |
| `dream` | 梦幻风格 — 柔焦朦胧、粉紫色调、超现实 |
| `dark` | 暗黑风格 — 低饱和、阴郁氛围、哥特元素 |
| `pixel` | 像素风格 — 复古游戏、8-bit、点阵画面 |

**题材类型 `genre`**：

| 值 | 说明 |
|------|------|
| `urban` | 都市情感 — 现代城市背景、职场/恋爱/家庭 |
| `suspense` | 悬疑推理 — 悬念迭起、推理破案、心理博弈 |
| `romance` | 甜蜜恋爱 — 浪漫邂逅、甜蜜互动、情感纠葛 |
| `action` | 动作热血 — 激烈打斗、追逐场面、英雄主义 |
| `comedy` | 轻松喜剧 — 幽默搞笑、反转误会、欢乐日常 |
| `horror` | 惊悚恐怖 — 阴森氛围、恐怖元素、心理压迫 |
| `scifi` | 科幻未来 — 太空/未来/科技、赛博元素 |
| `historical` | 古装历史 — 古代背景、宫廷/武侠/历史 |
| `campus` | 校园青春 — 校园生活、青春成长、同学情谊 |
| `family` | 家庭温情 — 亲情温暖、家庭矛盾、成长治愈 |
| `fantasy_xuanhuan` | 玄幻仙侠 — 修仙升级、法术对决、异界大陆 |
| `wuxia` | 武侠江湖 — 刀光剑影、侠义恩仇、武林纷争 |
| `mythology` | 神话传说 — 上古神兽、天宫地府、仙魔大战 |
| `adventure` | 冒险探索 — 未知世界、寻宝探险、极限挑战 |
| `workplace` | 职场商战 — 商业博弈、创业奋斗、办公室政治 |
| `sports` | 体育竞技 — 热血赛场、逆袭夺冠、团队拼搏 |
| `music_dance` | 音乐舞蹈 — 舞台梦想、唱跳练习、偶像成长 |
| `slice_of_life` | 日常治愈 — 慢节奏、小确幸、温馨日常 |
| `thriller` | 惊悚犯罪 — 高智商犯罪、心理博弈、正邪对决 |
| `war_military` | 战争军事 — 战场硝烟、军人荣耀、生死抉择 |
| `period` | 年代怀旧 — 80/90年代、老街旧巷、时代记忆 |
| `children` | 儿童亲子 — 童趣故事、寓教于乐、温馨陪伴 |

---

## 四、校验策略

### 4.1 校验优先级

**Schema 校验（入口处）→ 引用一致性校验 → 写入**

校验失败**立即终止**，返回具体错误位置，不进入半成品状态。

### 4.2 校验规则

```python
class ImportValidator:
    """导入数据校验器 — 严格模式，入口处拦截所有错误"""

    def validate(self, data: dict) -> tuple[ImportPlan | None, list[str]]:
        """
        Returns:
            (plan, []): 校验通过
            (None, errors): 校验失败，errors 包含所有错误信息
        """

        # 1. Schema 校验（Pydantic 自动完成）
        #    - 类型不匹配 → 立即报错
        #    - 必填字段缺失 → 立即报错
        #    - 枚举值不在范围内 → 立即报错
        #    - 字符串长度超限 → 立即报错

        # 2. 引用一致性校验
        #    - shots[].scene 必须在 scenes[].id 中存在
        #    - shots[].characters 中每个 ID 必须在 characters[].id 中存在
        #    - shots[].outfit 必须在对应角色的 outfits key 中存在

        # 3. 业务规则校验
        #    - shot_id 不得重复
        #    - 总时长建议 60-300 秒（警告，不阻断）
        #    - 每个镜头 duration 2-8 秒
```

### 4.3 错误信息格式

```json
{
  "status": "error",
  "errors": [
    "characters[2].id: 角色 ID 只允许字母、数字、下划线、连字符",
    "shots[5].scene: 引用的场景 'office' 不存在于 scenes 列表中",
    "shots[12].shot_id: 镜头 ID '001' 与 shots[0] 重复",
    "shots[8].duration: 时长 '12' 超出范围（2-8 秒）"
  ]
}
```

---

## 五、项目构建

校验通过后，原子性写入项目目录：

```python
class ProjectBuilder:
    """从 ImportPlan 原子性构建项目 — 要么全部成功，要么全部回滚"""

    def build(self, plan: ImportPlan, root: Path) -> Path:
        project_dir = root / "projects" / self._safe_name(plan.project_name)
        if project_dir.exists():
            raise ValueError(f"项目 '{plan.project_name}' 已存在，请更换名称或删除已有项目")

        try:
            # 1. 创建目录结构
            _ensure_project_dirs(project_dir)
            paths = ProjectPaths(project_dir)

            # 2. 写入 project.yaml（含 style/genre）
            _scaffold_default_config(project_dir, plan.project_name,
                                     style=plan.style, genre=plan.genre)

            # 3. 写入角色 YAML（含 outfits/voice 完整结构）
            for char in plan.characters:
                save_yaml(paths.character_yaml(char.id), {"character": char.model_dump()})

            # 4. 写入场景 YAML
            for scene in plan.scenes:
                save_yaml(paths.scene_yaml(scene.id), {"scene": scene.model_dump()})

            # 5. 写入分镜到 PostgreSQL
            if plan.shots:
                shots = [s.model_dump() for s in plan.shots]
                from engines.storyboard import save_storyboard
                save_storyboard(shots, episode=1)

            # 6. 写入完成（YAML 为唯一数据源，无需额外同步）

            return project_dir

        except Exception:
            # 写入失败时回滚：删除已创建的项目目录
            if project_dir.exists():
                shutil.rmtree(project_dir, ignore_errors=True)
            raise
```

---

## 六、入口

### 6.1 CLI

```bash
# 从 JSON 导入（创建新项目）
drama import plan.json

# 指定项目名（覆盖 JSON 中的 project_name）
drama import plan.json --name "我的短剧"

# 追加模式：向已有项目追加分镜（解决 LLM 输出截断）
drama import batch2.json --append
drama import batch3.json -a
```

### 6.2 Web API

```
POST /api/import/json
  Content-Type: application/json
  Body: ImportPlan JSON（含 "append": true 时为追加模式）

  → { task_id, poll_url }

GET /api/tasks/{task_id}
  → { status, progress, result }
```

### 6.3 Web 工作台

在 Web 工作台「📂 项目管理」页面增加「📥 导入剧本」入口，支持：

- 粘贴 JSON 文本
- 上传 `.json` 文件
- 导入前预览校验结果（角色数/场景数/镜头数/总时长）
- 校验失败时显示具体错误位置

---

## 七、Celery 任务

```python
@app.task(bind=True, name="pipeline_import_json", soft_time_limit=300)
def import_json_task(self, plan_data: dict) -> dict:
    """从 JSON 导入项目（异步）

    支持两种模式：
    - 全量导入：校验 → 构建项目目录 → 写入角色/场景/分镜（YAML 为唯一数据源）
    - 追加导入：append=True → 校验 → 向已有项目追加 shots
    """
    try:
        self.update_state(state="PROGRESS", meta={"step": "validate", "progress": 10, "message": "校验数据..."})

        # 1. Schema 校验（Pydantic 严格模式）
        plan = ImportPlan(**plan_data)
        is_append = plan.append

        # 2. 追加模式：加载已有项目的角色/场景/镜头 ID
        existing_char_ids, existing_scene_ids = None, None
        if is_append:
            existing_char_ids = {c["id"] for c in load_yaml_entities(char_dir, "character")}
            existing_scene_ids = {s["id"] for s in load_yaml_entities(scene_dir, "scene")}

        # 3. 引用一致性校验
        errors = ImportValidator.validate_references(plan, project_dir if is_append else None)
        if errors:
            return {"status": "error", "reason": "校验失败", "errors": errors}

        # 4. 全量/追加构建
        builder = ProjectBuilder()
        if is_append:
            result = builder.append(plan, root)
            return {"status": "done", "mode": "append",
                    "added_characters": result["added_characters"],
                    "added_scenes": result["added_scenes"],
                    "added_shots": result["added_shots"]}
        else:
            project_dir = builder.build(plan, root)
            return {"status": "done", "mode": "full",
                    "project_dir": str(project_dir),
                    "characters": len(plan.characters),
                    "scenes": len(plan.scenes),
                    "shots": len(plan.shots)}

    except ValidationError as e:
        errors = [f"{' → '.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in e.errors()]
        return {"status": "error", "reason": "数据格式错误", "errors": errors}
    except ValueError as e:
        return {"status": "error", "reason": str(e)}
    except Exception as e:
        logger.error(f"导入异常: {e}", exc_info=True)
        return {"status": "error", "reason": f"导入失败: {type(e).__name__}"}
```

---

## 八、Pydantic 模型

> 实际定义在 `infra/models.py`，Web Schema 在 `web/schemas/__init__.py`。

### 8.1 角色

```python
class ImportOutfit(BaseModel):
    description: str = Field(..., min_length=1, max_length=500)
    description_en: str = Field("", max_length=1000, description="英文服装描述（可选，跳过 prepare 翻译）")

class ImportCharacter(BaseModel):
    id: str = Field(..., min_length=1, max_length=50)        # ^[a-zA-Z0-9_-]+$
    name: str = Field(..., min_length=1, max_length=100)
    gender: str = Field("", max_length=10)
    age: str = Field("", max_length=10)
    appearance: str = Field(..., min_length=10, max_length=2000)
    outfits: dict[str, ImportOutfit] | None = None
    # ── 可选：预翻译（提供则跳过 prepare） ──
    appearance_prompt_en: str = Field("", max_length=4000)
    body_features: str = Field("", max_length=2000)           # 伤疤/纹身/胎记等
```

### 8.2 场景

```python
class ImportScene(BaseModel):
    id: str = Field(..., min_length=1, max_length=50)        # ^[a-zA-Z0-9_-]+$
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=10, max_length=2000)
    lighting: str = Field("", max_length=200)
    # ── 可选：预翻译 ──
    description_en: str = Field("", max_length=4000)
    lighting_en: str = Field("", max_length=400)
```

### 8.3 分镜

```python
class ImportShot(BaseModel):
    episode: int = Field(1, ge=1)
    shot_id: str = Field(..., min_length=1, max_length=20)   # ^[a-zA-Z0-9_-]+$
    scene_id: str = Field(..., min_length=1, max_length=50)  # 匹配 scenes[].id
    characters: str = Field("", max_length=100)               # 多人用 + 连接
    action: str = Field(..., min_length=5, max_length=500)
    dialogue: str = Field("......", max_length=500)
    camera: str = Field("", max_length=50)
    shot_type: str = Field("", max_length=50)
    duration: int = Field(4, ge=2, le=8)                      # 2-8 秒
    emotion: str = Field("neutral", max_length=30)
    outfit: str = Field("default", max_length=50)
    language: str = Field("zh", max_length=5)
    # ── 可选：预翻译 ──
    action_en: str = Field("", max_length=2000)
    dialogue_en: str = Field("", max_length=1000)
```

### 8.4 顶层

```python
class ImportPlan(BaseModel):
    """支持全量导入和追加导入两种模式"""
    project_name: str = Field("", max_length=100)
    style: str = Field("cinematic", max_length=50)
    genre: str = Field("urban", max_length=50)
    synopsis: str = Field("", max_length=500)
    episodes: int = Field(1, ge=1, le=100)
    episodes_summary: str = Field("", max_length=2000)        # 集数概要
    characters: list[ImportCharacter] = Field(default_factory=list)
    scenes: list[ImportScene] = Field(default_factory=list)
    shots: list[ImportShot] = Field(default_factory=list)
    append: bool = Field(False)                                # 追加模式
```

### 8.5 翻译状态检测

```python
def get_translation_status(plan: ImportPlan) -> dict:
    """检测导入计划的翻译完整度

    Returns:
        {
            "complete": bool,
            "missing": {"characters": [...], "scenes": [...], "shots": [...]},
            "summary": str,
        }
    """
```

提供 `*_en` 字段时跳过 prepare 阶段的 LLM 翻译，直接进入生产管线。

---

## 九、用户使用指南（复制粘贴到三方平台）

### 9.1 使用方式

1. 打开 DeepSeek / Kimi / 豆包 / MiMo Pro 等 AI 对话平台
2. 复制下方提示词模板，粘贴到对话框
3. 将 `{剧本内容}` 替换为你的实际剧本
4. 将 `{项目名}` / `{风格}` / `{题材}` / `{时长}` 替换为实际值
5. 发送，等待 AI 输出 JSON
6. 复制 AI 返回的 JSON（确保是完整合法的 JSON）
7. 到本系统「📂 项目管理 → 📥 导入剧本」粘贴导入

### ⚠ 重要：分批生成策略（解决输出截断）

**问题**：完整剧本 200+ 镜头，LLM 输出会被截断，JSON 不完整无法导入。

**解决**：分多轮对话生成，每轮 30-50 个镜头，分别导入。

| 轮次 | 生成内容 | 导入方式 |
|------|---------|---------|
| 第 1 轮 | 角色 + 场景 + 镜头 001-050 | `drama import batch1.json`（全量创建） |
| 第 2 轮 | 镜头 051-100 | `drama import batch2.json --append`（追加） |
| 第 3 轮 | 镜头 101-150 | `drama import batch3.json --append`（追加） |
| 第 4 轮 | 镜头 151-200+ | `drama import batch4.json --append`（追加） |

**每轮对话中，修改提示词的镜头范围即可**（如"第 001-050 个镜头"改为"第 051-100 个镜头"）。

### 9.2 提示词模板（BRTR 框架，直接复制使用）

**第 1 轮：角色 + 场景 + 前 50 个镜头**

```
【B - 说背景】
我正在使用一套 AI 短剧生产管线，需要将剧本提取为结构化 JSON 数据。
该管线会自动完成：TTS 语音合成 → AI 首帧图片生成 → 视频生成 → 口型同步 → 后期合成。
因此分镜数据需要精确到每个镜头的景别、运镜、情绪、服装，以确保生成画面的连贯性和一致性。

【R - 定角色】
你现在是一名资深影视分镜策划师 + AI 短剧制作专家，拥有丰富的影视分镜拆解经验。
你精通：
- 影视镜头语言（景别、运镜、蒙太奇剪辑）
- 角色视觉一致性管理（服装、造型、情绪的跨镜头统一）
- AI 视频生成的提示词逻辑（主体→动作→环境→镜头→风格）
- 短剧节奏把控（前3秒抓人、情绪起伏、反转设计）

【T - 派任务】
请将我提供的剧本内容提取为结构化 JSON 数据。

⚠ 重要：由于完整剧本镜头数量很多，请按以下分批策略输出：
- 本轮只输出：角色列表 + 场景列表 + 第 001-050 个镜头
- 后续镜头我会在下一轮对话中让你继续输出
- 确保本轮输出的 JSON 是完整、可解析的，不要截断

请严格按以下顺序完成：

① 先提取所有【角色】信息，每个角色必须包含：
   - id（英文小写下划线）、name、gender、age
   - appearance（10-2000字外貌描述，包含年龄/发型/五官/身材/肤色/气质）
   - personality（性格特征）
   - voice.voice_description（声音特征，用于 TTS 合成）
   - outfits（至少 default 服装，描述需具体到款式/颜色/配饰）

② 再提取所有【场景】信息，每个场景必须包含：
   - id（英文小写下划线）、name
   - description（10-2000字场景描述，包含空间布局/家具/装饰/色调）
   - lighting（光照描述，包含光源方向/色温/时间段）

③ 最后生成【分镜表 — 第 001-050 个镜头】，每个镜头必须包含：
   - episode、shot_id（三位数字001起递增）
   - scene（匹配场景 id）、characters（匹配角色 id，多人用+连接）
   - action（5-500字画面描述，按"主体→动作→环境→情绪"结构）
   - dialogue（中文台词，无台词填 "......"）
   - camera、shot_type、duration、emotion、outfit（匹配角色 outfits key）

【R - 提要求】
1. 输出严格合法 JSON，不要包含注释、解释、Markdown 代码块或多余文字
2. 角色形象绝对统一：每个镜头的 action 开头必须复用角色 appearance 的核心外貌特征，仅改变动作/表情/姿态，不能改动角色外貌设定
3. 场景描述绝对统一：同一场景在不同镜头中必须保持一致的空间布局和色调氛围
4. 服装连贯性：同一场景连续镜头中角色服装必须一致，换装必须有剧情依据
5. 每个镜头时长 2-8 秒，总时长控制在目标范围内
6. action 描述必须包含具体的动作、表情、姿态、环境细节
7. 节奏控制：开头镜头建立氛围，中段推进剧情，结尾留悬念或情感升华
8. 情绪递进：相邻镜头的情绪变化需有逻辑过渡，避免突兀跳跃

【可用值速查】
景别：特写、近景、中景、过肩、全身、全景、远景
运镜：固定、缓慢推近、跟随平移、手持晃动、环绕、俯视、仰视
情绪：happy、sad、worried、surprised、angry、calm、neutral

【项目信息】
- 项目名：{项目名}
- 视觉风格：{风格}（{风格说明}）
- 题材类型：{题材}（{题材说明}）
- 目标时长：{时长} 秒

请将以下剧本提取为 JSON（第 001-050 个镜头）：

{剧本内容}
```

**第 2+ 轮：继续输出后续镜头**

```
继续输出第 051-100 个镜头的 JSON。

要求：
1. 保持与前一轮完全一致的角色 ID、场景 ID、服装 key
2. shot_id 从 051 开始递增
3. 只输出 shots 数组，不需要重复角色和场景
4. 输出格式：{"shots": [...]}，不要其他字段
5. 确保 JSON 完整可解析，不要截断

前一轮的最后一个镜头信息（用于衔接）：
- shot_id: 050
- scene: {上一轮最后镜头的场景}
- characters: {上一轮最后镜头的角色}
- action: {上一轮最后镜头的动作}
```

### 9.3 快速填写示例

假设用户要导入一个都市爱情短剧（30 分钟，约 200 个镜头），使用 MiMo Pro 时的操作步骤：

**第 1 轮（角色 + 场景 + 镜头 001-050）：**

1. 打开 MiMo Pro
2. 粘贴上方「第 1 轮」模板
3. 修改占位符：`{项目名}` → `都市恋歌`，`{风格}` → `cinematic`，`{题材}` → `romance`，`{时长}` → `1800`
4. 在末尾粘贴实际剧本内容
5. 发送，等待 MiMo Pro 输出 JSON
6. 全选复制 JSON 文本
7. 保存为 `batch1.json`，执行：`drama import batch1.json`

**第 2 轮（镜头 051-100）：**

1. 在同一对话中继续，粘贴「第 2+ 轮」模板
2. 修改镜头范围和衔接信息
3. 发送，复制 JSON，保存为 `batch2.json`
4. 执行：`drama import batch2.json --append`

**第 3-4 轮同理**，每次修改镜头范围即可。

### 9.4 AI 输出不符合预期时的处理

如果 AI 输出的 JSON 不符合 Schema（缺字段、类型错误等），可以在对话中追加：

```
请修正以下问题后重新输出完整 JSON：
1. {具体问题描述}
2. {具体问题描述}

严格按之前的 Schema 输出，不要遗漏任何字段。
```

### 9.5 校验失败时的处理

导入时如果校验失败，系统会返回具体错误位置：

```json
{
  "status": "error",
  "reason": "数据格式错误",
  "errors": [
    "characters[2].id: 角色 ID 只允许字母、数字、下划线、连字符",
    "shots[5].scene: 引用的场景 'office' 不存在于 scenes 列表中",
    "shots[12].shot_id: 镜头 ID '001' 与 shots[0] 重复"
  ]
}
```

将错误信息复制回三方平台，让 AI 修正后重新导入。

| 现有模块 | 复用方式 |
|---------|---------|
| `engines/storyboard.py` | `save_storyboard()` 写入 PostgreSQL |
| `infra/config.py` | `ProjectPaths` / `save_yaml` 写配置 |
| `scripts/project_mgr.py` | `_ensure_project_dirs()` / `_scaffold_default_config()` 创建项目 |
| `infra/database/` | 分镜/生成状态 DB 操作（角色/场景以 YAML 为唯一数据源） |
| `config/system.yaml` | 风格/题材预设读取 |

---

## 十、文件清单

```
核心文件：
  infra/models.py              ImportPlan / ImportValidator / normalize_character
  pipeline/tasks/training_tasks.py  import_json_task（全量+追加双模式）
  cli/io.py                    import / export 命令
  web/routers/imports.py       项目管理 / 导入 / Seko / 训练路由
  scripts/project_builder.py   ProjectBuilder 原子性构建
  scripts/project_mgr.py       项目管理（新建/切换/删除）
  engines/storyboard.py        save_storyboard / append_storyboard（DB 写入）
  docs/internal/script-import-design.md  本文档
```

---

## 十一、完整示例

```json
{
  "project_name": "都市恋歌",
  "style": "cinematic",
  "genre": "romance",
  "synopsis": "林夏和顾辰在都市中相遇、相知、相爱的故事",
  "characters": [
    {
      "id": "linxia",
      "name": "林夏",
      "gender": "female",
      "age": "22",
      "appearance": "22岁，长发及腰，温柔的眼神，身材娇小，皮肤白皙，瓜子脸，大眼睛",
      "outfits": {
        "default": {
          "description": "白色连衣裙，简约优雅，腰间系一条细银色腰带，白色平底鞋"
        },
        "casual": {
          "description": "浅蓝色牛仔裤配白色宽松T恤，白色帆布鞋，休闲随意"
        },
        "formal": {
          "description": "黑色小西装外套，白色衬衫，黑色及膝裙，黑色高跟鞋"
        }
      }
    },
    {
      "id": "guchen",
      "name": "顾辰",
      "gender": "male",
      "age": "25",
      "appearance": "25岁，短发干净利落，剑眉星目，身材高挑挺拔，下颌线分明",
      "outfits": {
        "default": {
          "description": "深灰色休闲西装，白色圆领T恤，黑色休闲皮鞋"
        },
        "casual": {
          "description": "黑色卫衣，深色牛仔裤，白色运动鞋"
        }
      }
    }
  ],
  "scenes": [
    {
      "id": "living_room",
      "name": "客厅",
      "description": "现代简约客厅，落地窗暖光，木质地板，米色布艺沙发，墙上挂着抽象画，茶几上放着几本书",
      "lighting": "自然光从落地窗洒入，暖色调，黄昏时分有金色余晖"
    },
    {
      "id": "street",
      "name": "街道",
      "description": "繁华都市商业街，霓虹灯闪烁，人来人往，路边有咖啡店和花店",
      "lighting": "夜晚霓虹灯光，冷暖色调交织，路面有雨后反光"
    }
  ],
  "shots": [
    {
      "episode": 1,
      "shot_id": "001",
      "scene_id": "living_room",
      "characters": "linxia",
      "action": "林夏坐在沙发上，双腿蜷缩在身侧，低头翻看着手机，眉头微皱，手指在屏幕上犹豫地滑动",
      "dialogue": "他怎么还不回消息...",
      "camera": "缓慢推近",
      "shot_type": "近景",
      "duration": 5,
      "emotion": "worried",
      "outfit": "default"
    },
    {
      "episode": 1,
      "shot_id": "002",
      "scene_id": "living_room",
      "characters": "linxia",
      "action": "林夏把手机扣在沙发上，起身走到落地窗前，双手抱臂望向窗外的城市夜景",
      "dialogue": "......",
      "camera": "固定",
      "shot_type": "全身",
      "duration": 4,
      "emotion": "sad",
      "outfit": "default"
    },
    {
      "episode": 1,
      "shot_id": "003",
      "scene_id": "street",
      "characters": "guchen",
      "action": "顾辰撑着黑色雨伞走在湿漉漉的街道上，路过花店时停下脚步，目光落在橱窗里的一束白玫瑰上",
      "dialogue": "......",
      "camera": "跟随平移",
      "shot_type": "全身",
      "duration": 5,
      "emotion": "calm",
      "outfit": "default"
    },
    {
      "episode": 1,
      "shot_id": "004",
      "scene_id": "street",
      "characters": "guchen+linxia",
      "action": "顾辰抬头，隔着雨幕和花店的玻璃窗，与正在对面人行道上等红灯的林夏四目相对",
      "dialogue": "......",
      "camera": "固定",
      "shot_type": "过肩",
      "duration": 3,
      "emotion": "surprised",
      "outfit": "default"
    }
  ]
}
```
