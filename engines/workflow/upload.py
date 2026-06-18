"""上传映射 — 参考图上传映射"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from engines.utils.shot import parse_char_names
from engines.workflow.utils import find_load_image_nodes

logger = logging.getLogger(__name__)

__all__ = ["build_upload_map", "group_ipa_ref_nodes"]


def build_upload_map(builder, shot: dict, wf: dict) -> dict[str, str]:
    """构建参考图上传映射"""
    uploads: dict[str, str] = {}
    char_names = parse_char_names(shot)

    all_load_nodes = find_load_image_nodes(wf)

    ipa_primary_nodes = [n for n in all_load_nodes if n.startswith("ipadapter_ref_") and not n.startswith("ipadapter_ref2_")]
    ipa_secondary_nodes = [n for n in all_load_nodes if n.startswith("ipadapter_ref2_")]
    pulid_primary_nodes = [n for n in all_load_nodes if n.startswith("pulid_ref_") and not n.startswith("pulid_ref2_")]
    pulid_secondary_nodes = [n for n in all_load_nodes if n.startswith("pulid_ref2_")]
    controlnet_ref_nodes = [n for n in all_load_nodes if n.startswith("controlnet_ref_")]
    # Shakker-Labs Flux IP-Adapter: 参考图前缀 flux_ref_
    flux_ipa_primary_nodes = [n for n in all_load_nodes if n.startswith("flux_ref_") and not n.startswith("flux_ref2_")]
    flux_ipa_secondary_nodes = [n for n in all_load_nodes if n.startswith("flux_ref2_")]
    ipa_node_set = (set(ipa_primary_nodes) | set(ipa_secondary_nodes)
                    | set(pulid_primary_nodes) | set(pulid_secondary_nodes)
                    | set(controlnet_ref_nodes)
                    | set(flux_ipa_primary_nodes) | set(flux_ipa_secondary_nodes))
    scene_nodes = [n for n in all_load_nodes if n not in ipa_node_set
                   and not n.startswith("ipadapter_")
                   and not n.startswith("pulid_")
                   and not n.startswith("controlnet_ref_")
                   and not n.startswith("flux_ref_")]

    img_backend = builder.models.get("image_backend", "flux")
    ip_config = builder.config.get("ip_adapter", {})
    if img_backend == "flux":
        flux_config = builder.config.get("ip_adapter_flux", {})
        if flux_config and flux_config.get("enabled") is not False:
            ip_config = flux_config

    if char_names:
        refs = builder._get_character_refs(char_names[0], _no_auto_gen=builder.no_auto_gen, ip_config=ip_config)

        if refs and ipa_primary_nodes:
            ref_groups = group_ipa_ref_nodes(ipa_primary_nodes)
            if ref_groups:
                group = ref_groups[0]
                for i, ref_path in enumerate(refs):
                    if i < len(group):
                        uploads[group[i]] = ref_path
        elif refs and pulid_primary_nodes:
            uploads[pulid_primary_nodes[0]] = refs[0]
        elif refs and all_load_nodes:
            uploads[all_load_nodes[0]] = refs[0]

        # Flux IP-Adapter (Shakker-Labs) 参考图映射
        if refs and flux_ipa_primary_nodes:
            uploads[flux_ipa_primary_nodes[0]] = refs[0]

        if controlnet_ref_nodes and refs:
            resolved_id = builder._char_name_to_id.get(char_names[0], char_names[0])
            full_body = builder._paths.full_body_ref(resolved_id)
            if not full_body and refs:
                full_body = Path(refs[0])
            if full_body and full_body.exists():
                uploads[controlnet_ref_nodes[0]] = str(full_body)

    for i, cid in enumerate(char_names[1:]):
        refs = builder._get_character_refs(cid, _no_auto_gen=builder.no_auto_gen, ip_config=ip_config)
        if refs and ipa_secondary_nodes:
            ref_groups = group_ipa_ref_nodes(ipa_secondary_nodes)
            if i < len(ref_groups):
                group = ref_groups[i]
                for j, ref_path in enumerate(refs):
                    if j < len(group):
                        uploads[group[j]] = ref_path
        elif refs:
            secondary_pool = pulid_secondary_nodes + ipa_secondary_nodes + flux_ipa_secondary_nodes
            if i < len(secondary_pool):
                uploads[secondary_pool[i]] = refs[0]

        # Flux IP-Adapter (Shakker-Labs) 次要角色参考图映射
        if refs and flux_ipa_secondary_nodes and i < len(flux_ipa_secondary_nodes):
            uploads[flux_ipa_secondary_nodes[i]] = refs[0]

    depth_map = shot.get("depth_map", "")
    scene_ref = shot.get("scene_ref", "")
    if depth_map and scene_nodes:
        uploads[scene_nodes[0]] = depth_map
    elif scene_ref and scene_nodes:
        uploads[scene_nodes[0]] = scene_ref

    return uploads


def group_ipa_ref_nodes(nodes: list[str]) -> list[list[str]]:
    """将 ipadapter_ref_* 节点按 suffix 分组"""
    groups: dict[str, list[str]] = {}
    pattern = re.compile(r'^ipadapter_ref_(\d+)_(\d+)$')
    for n in nodes:
        m = pattern.match(n)
        if m:
            suffix = m.group(1)
            groups.setdefault(suffix, []).append(n)
    result = []
    for suffix in sorted(groups.keys()):
        group = sorted(groups[suffix], key=lambda x: int(pattern.match(x).group(2)))
        result.append(group)
    return result
