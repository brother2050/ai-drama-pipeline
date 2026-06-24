"""ComfyUI 工作流 Diff 层 — 支持工作流 JSON 的对比和预览

WorkflowDiffer: 工作流差异比较器，提供 unified diff 和结构化摘要
"""
from __future__ import annotations

import difflib
import json

__all__ = ["WorkflowDiffer"]


class WorkflowDiffer:
    """工作流差异比较器

    提供两种对比方式:
    1. diff(): 生成 unified diff 格式的工作流差异文本
    2. summary(): 生成结构化差异摘要（added/removed/modified 节点列表 + 总数）
    """

    def diff(self, before: dict, after: dict) -> str:
        """生成 unified diff 格式的工作流差异

        Args:
            before: 变更前的工作流 JSON
            after: 变更后的工作流 JSON

        Returns:
            unified diff 格式的差异文本
        """
        before_str = json.dumps(before, sort_keys=True, indent=2, ensure_ascii=False)
        after_str = json.dumps(after, sort_keys=True, indent=2, ensure_ascii=False)
        diff_lines = difflib.unified_diff(
            before_str.splitlines(keepends=True),
            after_str.splitlines(keepends=True),
            fromfile="before",
            tofile="after",
        )
        return "".join(diff_lines)

    def summary(self, before: dict, after: dict) -> dict:
        """生成结构化差异摘要

        Args:
            before: 变更前的工作流 JSON
            after: 变更后的工作流 JSON

        Returns:
            包含 added/removed/modified 节点列表和总数的字典::

                {
                    "added": ["node_id_1", ...],
                    "removed": ["node_id_2", ...],
                    "modified": ["node_id_3", ...],
                    "total_added": int,
                    "total_removed": int,
                    "total_modified": int,
                }
        """
        before_nodes = {k: v for k, v in before.items() if not k.startswith("_")}
        after_nodes = {k: v for k, v in after.items() if not k.startswith("_")}

        before_ids = set(before_nodes.keys())
        after_ids = set(after_nodes.keys())

        added = sorted(after_ids - before_ids)
        removed = sorted(before_ids - after_ids)
        modified = sorted(
            nid for nid in (before_ids & after_ids)
            if before_nodes[nid] != after_nodes[nid]
        )

        return {
            "added": added,
            "removed": removed,
            "modified": modified,
            "total_added": len(added),
            "total_removed": len(removed),
            "total_modified": len(modified),
        }
