"""定妆照生成 — Celery 编排层

核心生成逻辑全部委托给 engines/portrait.py。
本模块只负责：遍历角色 → 调用 engines → 汇总结果。
"""
from __future__ import annotations

from infra.constants import STATUS_DONE
import logging

from infra.config import Config, load_yaml_full

logger = logging.getLogger(__name__)


def run_portraits(
    config_path: str,
    *,
    force: bool = False,
    char_ids: list[str] | None = None,
    write_db: bool = False,
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
            data = load_yaml_full(f)
        except Exception as e:
            logger.warning(f"角色 YAML 格式错误 {f}: {e}")
            continue

        char = data.get("character", {})
        char_id = char.get("id", "")
        if not char_id:
            continue

        logger.info(f"  角色: {char.get('name', char_id)} ({char_id})")
        if not cont:
            logger.warning("    ⚠ 无 ComfyUI 连接，跳过")
            continue

        try:
            from engines.portrait import ensure_portrait
            result = ensure_portrait(char_id, cfg.data, container=cont, force=force)
            if result:
                generated += 1
                logger.info("    ✅ 定妆照完成")
            else:
                logger.warning("    ⚠ 定妆照未生成")

            # 写回 YAML（ensure_portrait 已更新 reference_images）
            if write_db and result:
                from infra.config import save_yaml
                # 重新读取最新数据（ensure_portrait 可能已修改）
                latest = load_yaml_full(f)
                save_yaml(f, latest)
                logger.info("    📝 已更新 YAML")

        except Exception as e:
            logger.error(f"    ❌ 失败: {e}", exc_info=True)

    logger.info(f"定妆照生成完成 ({generated} 个角色)")
    return {"status": STATUS_DONE, "generated": generated, "total": len(char_files)}
