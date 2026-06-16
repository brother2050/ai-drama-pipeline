"""定妆照生成 — Celery 编排层

核心生成逻辑全部委托给 engines/portrait.py。
本模块只负责：遍历角色 → 调用 engines → 汇总结果。
"""
from __future__ import annotations

from infra.constants import STATUS_DONE, STATUS_ERROR
import logging

from infra.config import Config

logger = logging.getLogger(__name__)


def run_portraits(
    config_path: str,
    *,
    force: bool = False,
    char_ids: list[str] | None = None,
) -> dict:
    """批量生成定妆照（五视图 + 各服装参考图）

    核心逻辑委托给 engines/portrait.ensure_portrait()。
    本函数只负责遍历角色 + 汇总结果。
    """
    cfg = Config(config_path)
    paths = cfg.paths
    logger.info("生成定妆照（五视图）")

    from api.registry import Container
    chars_dir = paths.characters_dir
    if not chars_dir.exists():
        logger.warning("角色配置目录不存在")
        return {"status": STATUS_DONE, "generated": 0, "total": 0}

    try:
        cont = Container(cfg.data)
    except Exception as e:
        logger.warning(f"无法创建容器: {e}")
        cont = None

    # 确定要处理的角色文件列表
    if char_ids is not None:
        char_files = [chars_dir / f"{cid}.yaml" for cid in char_ids
                      if (chars_dir / f"{cid}.yaml").exists()]
    else:
        from infra.config import load_yaml_entities
        char_files = [f for f, _ in load_yaml_entities(chars_dir, "character", with_paths=True)]

    generated = 0
    for f in char_files:
        try:
            from infra.config import load_character
            char = load_character(chars_dir, f.stem)
        except Exception as e:
            logger.warning(f"角色 YAML 格式错误 {f}: {e}")
            continue

        char_id = char.get("id", "")
        if not char_id:
            continue

        logger.info(f"  角色: {char.get('name', char_id)} ({char_id})")
        if not cont:
            logger.warning("    ⚠ 无 ComfyUI 连接，跳过")
            continue

        try:
            from engines.content.portrait import ensure_portrait
            result = ensure_portrait(char_id, cfg.data, container=cont, force=force)
            if result:
                generated += 1
                logger.info("    ✅ 定妆照完成")
            else:
                logger.warning("    ⚠ 定妆照未生成")

        except Exception as e:
            logger.error(f"    ❌ 失败: {e}", exc_info=True)

    logger.info(f"定妆照生成完成 ({generated} 个角色)")
    if generated == 0 and len(char_files) > 0:
        return {"status": STATUS_ERROR, "reason": f"0/{len(char_files)} 个角色的定妆照生成失败（可能缺少英文描述或 ComfyUI 不可用）",
                "generated": 0, "total": len(char_files)}
    return {"status": STATUS_DONE, "generated": generated, "total": len(char_files)}
