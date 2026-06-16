"""默认分镜种子数据 — 新项目自动写入 DB

分镜的 characters/scene_name 存中文名（供 LLM 读取），
文件名/DB 主键用 hash ID（由 name_to_id 自动生成）。
"""

DEFAULT_CHARACTERS = [
    {
        "id": "2df5a0", "name": "林夏", "gender": "female", "age": "22",
        "appearance": "22岁年轻女性，长发及肩，瓜子脸，大眼睛，柳叶眉，身高165cm，体型偏瘦，皮肤白皙",
        "outfits": {
            "default": {"description": "白色T恤，浅蓝色牛仔裤，白色帆布鞋，斜挎小包", "reference_images": []},
            "home": {"description": "浅粉色居家服，棉拖鞋", "reference_images": []},
        },
        "bible": {
            "core_traits": "温柔但坚强，容易害羞，对顾辰有好感",
            "speech_patterns": "语速较慢，常用'嗯...'开头，不说脏话",
            "relationships": {"顾辰": "暗恋对象，相处时会紧张"},
            "emotional_range": {"happy": "微笑为主，不会大笑", "sad": "沉默，不哭出声"},
            "body_language": {"nervous": "低头，手指绞在一起", "happy": "眼睛弯成月牙"},
        },
    },
    {
        "id": "9dbae1", "name": "顾辰", "gender": "male", "age": "22",
        "appearance": "22岁年轻男性，短发，剑眉星目，身高180cm，体型匀称",
        "outfits": {
            "default": {"description": "黑色卫衣，深色休闲裤，运动鞋，双肩包", "reference_images": []},
        },
        "bible": {
            "core_traits": "沉稳可靠，行动派，对林夏有好感但不善表达",
            "speech_patterns": "语速适中，简洁直接，偶尔会突然关心人",
            "relationships": {"林夏": "喜欢的人，会默默关注和保护"},
            "emotional_range": {"happy": "嘴角微扬，眼神温柔", "angry": "沉默不语，眉头紧锁"},
            "body_language": {"nervous": "挠头，眼神躲闪", "happy": "嘴角上扬，眼神明亮"},
        },
    },
]

DEFAULT_SCENES = [
    {
        "id": "c151cd", "name": "客厅",
        "description": "现代简约风格客厅，米色沙发，落地窗，暖色调灯光，茶几上有水杯和手机",
        "lighting": "暖色室内光，自然光从窗户照入",
    },
    {
        "id": "ee10a1", "name": "街道",
        "description": "城市街道，两侧有商铺和行道树，路面为柏油路，远处可见高楼天际线，傍晚暖色调天光",
        "lighting": "傍晚自然光，暖色调，路灯微亮",
    },
]

# 分镜中 characters/scene_name 存中文名（LLM 生成和读取都用中文名）
DEFAULT_SHOTS = [
    {"shot_id": "001", "scene_name": "客厅", "characters": "林夏",
     "action": "坐在沙发上看手机", "dialogue": "他怎么还不回消息...",
     "camera": "缓慢推近", "shot_type": "特写", "duration": "4", "outfit": "home", "emotion": "worried",
     "action_en": "sitting on sofa looking at phone", "dialogue_en": "Why isn't he replying..."},
    {"shot_id": "002", "scene_name": "客厅", "characters": "林夏",
     "action": "起身走到窗前", "dialogue": "......",
     "camera": "跟随平移", "shot_type": "中景", "duration": "3", "outfit": "home", "emotion": "sad",
     "action_en": "stands up and walks to the window", "dialogue_en": "..."},
    {"shot_id": "003", "scene_name": "街道", "characters": "顾辰",
     "action": "骑车赶路", "dialogue": "马上就到了！",
     "camera": "固定", "shot_type": "全身", "duration": "4", "outfit": "default", "emotion": "determined",
     "action_en": "riding a bicycle", "dialogue_en": "I'm almost there!"},
    {"shot_id": "004", "scene_name": "客厅", "characters": "林夏",
     "action": "听到门铃声抬头", "dialogue": "嗯？",
     "camera": "手持晃动", "shot_type": "近景", "duration": "2", "outfit": "home", "emotion": "surprised",
     "action_en": "hears the doorbell and looks up", "dialogue_en": "Hmm?"},
    {"shot_id": "005", "scene_name": "街道", "characters": "顾辰",
     "action": "按门铃", "dialogue": "开门！我来了！",
     "camera": "固定", "shot_type": "近景", "duration": "3", "outfit": "default", "emotion": "happy",
     "action_en": "ringing the doorbell", "dialogue_en": "Open the door! I'm here!"},
    {"shot_id": "006", "scene_name": "客厅", "characters": "林夏+顾辰",
     "action": "开门对视", "dialogue": "......",
     "camera": "缓慢推近", "shot_type": "双人全景", "duration": "5", "outfit": "home", "emotion": "romantic",
     "action_en": "opens the door and they lock eyes", "dialogue_en": "..."},
    {"shot_id": "007", "scene_name": "客厅", "characters": "顾辰",
     "action": "递出一束花", "dialogue": "送你的，生日快乐。",
     "camera": "固定", "shot_type": "中景", "duration": "4", "outfit": "default", "emotion": "happy",
     "action_en": "handing over a bouquet of flowers", "dialogue_en": "This is for you. Happy birthday."},
    {"shot_id": "008", "scene_name": "客厅", "characters": "林夏",
     "action": "接过花低头笑", "dialogue": "谢谢...你还记得。",
     "camera": "缓慢推近", "shot_type": "特写", "duration": "4", "outfit": "home", "emotion": "romantic",
     "action_en": "takes the flowers and smiles", "dialogue_en": "Thank you... you remembered."},
]
