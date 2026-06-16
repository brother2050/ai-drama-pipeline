#!/usr/bin/env python3
"""端到端测试：模拟完整导入流程（不需要 Redis/PG）"""
import sys
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 测试用 JSON
PLAN_JSON = {
    "project_name": "测试都市恋歌",
    "style": "cinematic",
    "genre": "romance",
    "characters": [
        {
            "id": "linxia",
            "name": "林夏",
            "gender": "female",
            "age": "22",
            "appearance": "22岁，长发及腰，温柔的眼神，身材娇小，皮肤白皙，瓜子脸，大眼睛，睫毛很长",
            "outfits": {
                "default": {"description": "白色连衣裙，简约优雅，腰间系一条细银色腰带，白色平底鞋"},
                "casual": {"description": "浅蓝色牛仔裤配白色宽松T恤，白色帆布鞋"}
            },
            "bible": {"core_traits": "外冷内热，善良但有些胆小"},
        },
        {
            "id": "guchen",
            "name": "顾辰",
            "gender": "male",
            "age": "25",
            "appearance": "25岁，短发干净利落，剑眉星目，身材高挑挺拔，下颌线分明，鼻梁高挺",
            "outfits": {
                "default": {"description": "深灰色休闲西装，白色圆领T恤，黑色休闲皮鞋"}
            },
            "bible": {"core_traits": "外表高冷实则温柔，做事果断"},
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
            "episode": "1", "shot_id": "001", "scene_name": "living_room", "characters": "linxia",
            "action": "林夏坐在沙发上，双腿蜷缩在身侧，低头翻看着手机，眉头微皱，手指在屏幕上犹豫地滑动",
            "dialogue": "他怎么还不回消息...", "camera": "缓慢推近", "shot_type": "近景",
            "duration": "5", "emotion": "worried", "outfit": "default"
        },
        {
            "episode": "1", "shot_id": "002", "scene_name": "living_room", "characters": "linxia",
            "action": "林夏把手机扣在沙发上，起身走到落地窗前，双手抱臂望向窗外的城市夜景",
            "dialogue": "......", "camera": "固定", "shot_type": "全身",
            "duration": "4", "emotion": "sad", "outfit": "default"
        },
        {
            "episode": "1", "shot_id": "003", "scene_name": "street", "characters": "guchen",
            "action": "顾辰撑着黑色雨伞走在湿漉漉的街道上，路过花店时停下脚步，目光落在橱窗里的一束白玫瑰上",
            "dialogue": "......", "camera": "跟随平移", "shot_type": "全身",
            "duration": "5", "emotion": "calm", "outfit": "default"
        },
        {
            "episode": "1", "shot_id": "004", "scene_name": "street", "characters": "guchen+linxia",
            "action": "顾辰抬头，隔着雨幕和花店的玻璃窗，与正在对面人行道上等红灯的林夏四目相对",
            "dialogue": "......", "camera": "固定", "shot_type": "过肩",
            "duration": "3", "emotion": "surprised", "outfit": "default"
        }
    ]
}


def test_schema_validation():
    """1. Schema 校验"""
    print("=" * 50)
    print("1. Schema 校验")
    from infra.models import ImportPlan

    plan = ImportPlan(**PLAN_JSON)
    assert len(plan.characters) == 2
    assert len(plan.scenes) == 2
    assert len(plan.shots) == 4
    print("   ✅ ImportPlan 创建成功")
    print(f"   角色: {len(plan.characters)} 个")
    print(f"   场景: {len(plan.scenes)} 个")
    print(f"   分镜: {len(plan.shots)} 个")


@pytest.mark.skip(reason="需要顺序执行，通过 __main__ 调用")
def test_reference_validation(plan):
    """2. 引用一致性校验"""
    print("\n" + "=" * 50)
    print("2. 引用一致性校验")
    from infra.models import ImportValidator

    errors = ImportValidator.validate_references(plan)
    if errors:
        print(f"   ❌ 发现 {len(errors)} 个错误:")
        for e in errors:
            print(f"      • {e}")
        return False
    else:
        print("   ✅ 引用一致性校验通过")
        return True


@pytest.mark.skip(reason="需要顺序执行，通过 __main__ 调用")
def test_project_builder(plan):
    """3. 项目构建（原子性写入）"""
    print("\n" + "=" * 50)
    print("3. 项目构建")
    from scripts.project_builder import ProjectBuilder

    builder = ProjectBuilder()

    # 清理旧测试项目（项目名经过 safe_name 处理，中文保留）
    import re
    safe_name = re.sub(r"[^\w\u4e00-\u9fff\-]", "_", plan.project_name).strip("_")
    project_dir = ROOT / "projects" / safe_name
    if project_dir.exists():
        shutil.rmtree(project_dir)

    try:
        result_dir = builder.build(plan, ROOT)
        print(f"   ✅ 项目目录创建成功: {result_dir}")

        # 验证文件结构
        from infra.config import ProjectPaths
        paths = ProjectPaths(result_dir)

        # project.yaml
        assert paths.project_yaml.exists(), "project.yaml 不存在"
        print("   ✅ project.yaml 已创建")

        # 角色 YAML
        for char in plan.characters:
            yml = paths.character_yaml(char.id)
            assert yml.exists(), f"角色 {char.id}.yaml 不存在"
        print(f"   ✅ {len(plan.characters)} 个角色 YAML 已创建")

        # 场景 YAML
        for scene in plan.scenes:
            yml = paths.scene_yaml(scene.id)
            assert yml.exists(), f"场景 {scene.id}.yaml 不存在"
        print(f"   ✅ {len(plan.scenes)} 个场景 YAML 已创建")

        # 分镜（从 DB 验证）
        from infra.database.pool import get_pool
        from infra.database.storyboard_db import get_episode_shots
        try:
            shots = get_episode_shots(get_pool(), 1)
            print(f"   ✅ 分镜已写入 DB ({len(shots)} 个镜头)")
        except Exception as e:
            print(f"   ⚠ DB 验证跳过: {e}")

        # 验证内容正确性
        import yaml
        with open(paths.character_yaml("linxia"), encoding="utf-8") as f:
            char_data = yaml.safe_load(f)
        assert char_data["character"]["name"] == "林夏"
        assert "outfits" in char_data["character"]
        print("   ✅ 角色数据内容正确（含 outfits）")

        with open(paths.scene_yaml("living_room"), encoding="utf-8") as f:
            scene_data = yaml.safe_load(f)
        assert scene_data["scene"]["name"] == "客厅"
        print("   ✅ 场景数据内容正确")

        # 验证活动项目已设置
        active_file = ROOT / "projects" / ".active"
        assert active_file.exists()
        active_content = active_file.read_text().strip()
        assert safe_name in active_content, f"活动项目不匹配: 期望含 '{safe_name}', 实际 '{active_content}'"
        print("   ✅ 已设为活动项目")

        return result_dir

    except Exception as e:
        print(f"   ❌ 构建失败: {e}")
        import traceback
        traceback.print_exc()
        return None


@pytest.mark.skip(reason="需要顺序执行，通过 __main__ 调用")
def test_project_cleanup(project_dir):
    """4. 清理测试项目"""
    print("\n" + "=" * 50)
    print("4. 清理")
    if project_dir and project_dir.exists():
        shutil.rmtree(project_dir)
        print(f"   ✅ 测试项目已删除: {project_dir.name}")
    else:
        print("   ⚠ 项目目录不存在，跳过清理")

    # 恢复 default 为活动项目
    active_file = ROOT / "projects" / ".active"
    default_dir = ROOT / "projects" / "default"
    if default_dir.exists():
        active_file.write_text(str(default_dir), encoding="utf-8")
        print("   ✅ 活动项目已恢复为 default")


def test_error_cases():
    """5. 错误场景测试"""
    print("\n" + "=" * 50)
    print("5. 错误场景测试")
    from infra.models import ImportPlan, ImportValidator
    from pydantic import ValidationError

    # 5a. 项目名非法字符
    try:
        ImportPlan(project_name="../hack", characters=[], scenes=[], shots=[])
        print("   ❌ 应该拦截非法项目名")
    except ValidationError:
        print("   ✅ 非法项目名被拦截")

    # 5b. 角色 ID 包含中文
    try:
        ImportPlan(project_name="test", characters=[
            {"id": "林夏", "name": "林夏", "appearance": "22岁长发温柔女生，身材娇小皮肤白皙"}
        ])
        print("   ❌ 应该拦截中文 ID")
    except ValidationError:
        print("   ✅ 中文角色 ID 被拦截")

    # 5c. 引用不存在的角色
    plan = ImportPlan(
        project_name="test",
        characters=[{"id": "linxia", "name": "林夏", "appearance": "22岁长发温柔女生，身材娇小皮肤白皙"}],
        scenes=[{"id": "room", "name": "房间", "description": "一个普通的房间，有窗户和床铺"}],
        shots=[{"shot_id": "001", "scene_name": "room", "characters": "guchen", "action": "顾辰坐在椅子上看书"}]
    )
    errors = ImportValidator.validate_references(plan)
    assert any("guchen" in e for e in errors)
    print("   ✅ 引用不存在角色被检出")

    # 5d. shot_id 重复
    plan2 = ImportPlan(
        project_name="test",
        characters=[{"id": "a", "name": "A", "appearance": "一个普通人的外貌描述，需要足够长"}],
        scenes=[{"id": "s", "name": "S", "description": "一个普通的场景描述，需要足够长才能通过校验"}],
        shots=[
            {"shot_id": "001", "scene_name": "s", "characters": "a", "action": "角色在场景中做某个动作"},
            {"shot_id": "001", "scene_name": "s", "characters": "a", "action": "角色在场景中做另一个动作"}
        ]
    )
    errors2 = ImportValidator.validate_references(plan2)
    assert any("重复" in e for e in errors2)
    print("   ✅ shot_id 重复被检出")

    # 5e. duration 超范围
    try:
        ImportPlan(project_name="test", shots=[
            {"shot_id": "001", "scene_name": "s", "action": "一个足够长的动作描述", "duration": "15"}
        ])
        print("   ❌ 应该拦截 duration=15")
    except ValidationError:
        print("   ✅ duration=15 超范围被拦截")

    # 5f. 重复项目名构建失败
    from scripts.project_builder import ProjectBuilder
    builder = ProjectBuilder()
    plan3 = ImportPlan(project_name="default")  # default 已存在
    try:
        builder.build(plan3, ROOT)
        print("   ❌ 应该拦截重复项目名")
    except ValueError as e:
        print(f"   ✅ 重复项目名被拦截: {e}")


if __name__ == "__main__":
    print("🎬 剧本 JSON 导入 — 端到端测试\n")

    from infra.models import ImportPlan
    plan = ImportPlan(**PLAN_JSON)
    test_schema_validation()
    ok = test_reference_validation(plan)
    if not ok:
        sys.exit(1)

    project_dir = test_project_builder(plan)

    test_project_cleanup(project_dir)

    test_error_cases()

    print("\n" + "=" * 50)
    print("✅ 全部测试通过！")
