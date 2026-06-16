#!/usr/bin/env python3
"""测试剧本 JSON 导入 — 纯本地验证（不需要 Redis/PostgreSQL）"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from infra.models import ImportPlan, ImportValidator  # noqa: E402


def test_valid_plan():
    """测试合法数据"""
    plan_data = {
        "project_name": "都市恋歌",
        "style": "cinematic",
        "genre": "romance",
        "characters": [
            {
                "id": "linxia",
                "name": "林夏",
                "gender": "female",
                "age": "22",
                "appearance": "22岁，长发及腰，温柔的眼神，身材娇小，皮肤白皙，瓜子脸，大眼睛",
                "outfits": {
                    "default": {"description": "白色连衣裙，简约优雅，腰间系一条细银色腰带"},
                    "casual": {"description": "浅蓝色牛仔裤配白色T恤，休闲随意"}
                },
                "bible": {"core_traits": "外冷内热，善良但有些胆小"},
            },
            {
                "id": "guchen",
                "name": "顾辰",
                "gender": "male",
                "age": "25",
                "appearance": "25岁，短发干净利落，剑眉星目，身材高挑挺拔，下颌线分明",
                "outfits": {
                    "default": {"description": "深灰色休闲西装，白色圆领T恤，黑色休闲皮鞋"}
                },
                "bible": {"core_traits": "外表高冷实则温柔"},
            }
        ],
        "scenes": [
            {
                "id": "living_room",
                "name": "客厅",
                "description": "现代简约客厅，落地窗暖光，木质地板，米色布艺沙发，墙上挂着抽象画",
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
                "episode": "1",
                "shot_id": "001",
                "scene_name": "客厅",
                "characters": "林夏",
                "action": "林夏坐在沙发上，双腿蜷缩在身侧，低头翻看着手机，眉头微皱，手指在屏幕上犹豫地滑动",
                "dialogue": "他怎么还不回消息...",
                "camera": "缓慢推近",
                "shot_type": "近景",
                "duration": "5",
                "emotion": "worried",
                "outfit": "default"
            },
            {
                "episode": "1",
                "shot_id": "002",
                "scene_name": "客厅",
                "characters": "林夏",
                "action": "林夏把手机扣在沙发上，起身走到落地窗前，双手抱臂望向窗外的城市夜景",
                "dialogue": "......",
                "camera": "固定",
                "shot_type": "全身",
                "duration": "4",
                "emotion": "sad",
                "outfit": "default"
            },
            {
                "episode": "1",
                "shot_id": "003",
                "scene_name": "街道",
                "characters": "顾辰",
                "action": "顾辰撑着黑色雨伞走在湿漉漉的街道上，路过花店时停下脚步，目光落在橱窗里的一束白玫瑰上",
                "dialogue": "......",
                "camera": "跟随平移",
                "shot_type": "全身",
                "duration": "5",
                "emotion": "calm",
                "outfit": "default"
            },
            {
                "episode": "1",
                "shot_id": "004",
                "scene_name": "街道",
                "characters": "顾辰+林夏",
                "action": "顾辰抬头，隔着雨幕和花店的玻璃窗，与正在对面人行道上等红灯的林夏四目相对",
                "dialogue": "......",
                "camera": "固定",
                "shot_type": "过肩",
                "duration": "3",
                "emotion": "surprised",
                "outfit": "default"
            }
        ]
    }

    plan = ImportPlan(**plan_data)
    errors = ImportValidator.validate_references(plan)
    assert errors == [], f"预期无错误，实际: {errors}"
    print(f"✅ 合法数据通过 — {len(plan.characters)} 角色, {len(plan.scenes)} 场景, {len(plan.shots)} 镜头")


def test_reference_errors():
    """测试引用错误检测（重复 shot_id + 缺失引用均报错）"""
    plan_data = {
        "project_name": "测试项目",
        "characters": [
            {"id": "linxia", "name": "林夏", "appearance": "22岁长发温柔女生，身材娇小"}
        ],
        "scenes": [
            {"id": "living_room", "name": "客厅", "description": "现代简约客厅落地窗暖光木质地板"}
        ],
        "shots": [
            {"shot_id": "001", "scene_name": "办公室", "characters": "顾辰", "action": "顾辰坐在办公桌前看文件，眉头紧锁"},
            {"shot_id": "001", "scene_name": "客厅", "characters": "林夏", "action": "林夏坐在沙发上翻手机"}
        ]
    }

    plan = ImportPlan(**plan_data)
    errors = ImportValidator.validate_references(plan)
    # 重复 shot_id 应报错
    assert any("shot_id" in e and "重复" in e for e in errors), f"预期 shot_id 重复错误，实际: {errors}"
    # 缺失的角色/场景也应报错
    assert any("办公室" in e and "不存在" in e for e in errors), f"预期场景缺失错误，实际: {errors}"
    assert any("顾辰" in e and "不存在" in e for e in errors), f"预期角色缺失错误，实际: {errors}"
    print(f"✅ 引用错误检测通过 — 发现 {len(errors)} 个错误:")
    for e in errors:
        print(f"   • {e}")


def test_shots_only_with_existing_project():
    """测试 shots-only JSON + 已有项目目录（两步导入场景）"""
    import tempfile
    from pathlib import Path
    from infra.config import save_yaml, ProjectPaths

    # 模拟已有项目目录
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir) / "test_project"
        paths = ProjectPaths(project_dir)
        paths.characters_dir.mkdir(parents=True, exist_ok=True)
        paths.scenes_dir.mkdir(parents=True, exist_ok=True)
        # 写入已有角色/场景
        save_yaml(paths.character_yaml("lu_zhou"), {"character": {"id": "lu_zhou", "name": "陆舟", "appearance": "一个年轻男子短发穿着深色外套"}})
        save_yaml(paths.scene_yaml("rainy_night_alley"), {"scene": {"id": "rainy_night_alley", "name": "雨夜小巷", "description": "一条狭窄的巷子雨水顺着墙壁流下"}})

        # shots-only JSON（无 characters/scenes 定义）
        plan = ImportPlan(**{
            "shots": [
                {"shot_id": "001", "scene_name": "雨夜小巷", "characters": "陆舟", "action": "陆舟独自走在雨巷中，雨水打湿了他的肩膀"}
            ]
        })

        errors = ImportValidator.validate_references(plan, project_dir=project_dir)
        assert errors == [], f"已有项目应能解析引用，实际: {errors}"
        print("✅ shots-only + 已有项目通过 — 0 错误")


def test_schema_errors():
    """测试 Schema 校验"""
    from pydantic import ValidationError

    # shot_id 包含非法字符
    try:
        ImportPlan(project_name="test", shots=[
            {"shot_id": "001@#", "scene_name": "s", "action": "测试动作描述内容"}
        ])
        print("❌ 应该报错但没报")
    except ValidationError:
        print("✅ Schema 校验通过 — shot_id 非法字符被拦截")

    # action 太短
    try:
        ImportPlan(project_name="test", shots=[
            {"shot_id": "001", "scene_name": "s", "action": "短"}
        ])
        print("❌ 应该报错但没报")
    except ValidationError:
        print("✅ Schema 校验通过 — action 太短被拦截")

    # duration 超范围
    try:
        ImportPlan(project_name="test", shots=[
            {"shot_id": "001", "scene_name": "s", "action": "测试动作描述内容", "duration": "15"}
        ])
        print("❌ 应该报错但没报")
    except ValidationError:
        print("✅ Schema 校验通过 — duration=15 超范围被拦截")


@pytest.mark.skip(reason="需要文件路径参数，通过 __main__ 调用")
def test_from_file(filepath: str):
    """从文件测试（仅 __main__ 调用）"""
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    plan = ImportPlan(**data)
    errors = ImportValidator.validate_references(plan)
    if errors:
        print(f"❌ 校验失败 — {len(errors)} 个错误:")
        for e in errors:
            print(f"   • {e}")
    else:
        print(f"✅ 校验通过 — {len(plan.characters)} 角色, {len(plan.scenes)} 场景, {len(plan.shots)} 镜头")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_from_file(sys.argv[1])
    else:
        print("=== 剧本 JSON 导入测试 ===\n")
        test_valid_plan()
        print()
        test_reference_errors()
        print()
        test_shots_only_with_existing_project()
        print()
        test_schema_errors()
        print()
        print("全部测试完成！")
        print("\n用法: python test_import.py <your_plan.json>")
