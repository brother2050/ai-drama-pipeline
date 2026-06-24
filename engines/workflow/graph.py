"""ComfyUI 节点模型层 — 用 dataclass 替代裸 dict，提供类型安全的节点操作

NodeRef: 节点引用（node_id + output_index），序列化为 ComfyUI [node_id, output_index] 格式
Node: 节点（node_id + class_type + inputs），提供 ref/set_input/get_input 等方法
WorkflowGraph: 工作流图（nodes dict），提供 add_node/find_by_class/to_dict/from_dict 等方法
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["Node", "NodeRef", "WorkflowGraph"]


@dataclass(frozen=True)
class NodeRef:
    """节点引用 — 指向某个节点的特定输出

    ComfyUI 中节点间的连线用 [node_id, output_index] 格式表示，
    NodeRef 将其封装为类型安全的对象，避免裸 list 操作的拼写错误。

    Attributes:
        node_id: 被引用节点的 ID
        output_index: 被引用节点的输出索引（通常为 0）
    """

    node_id: str
    output_index: int = 0

    def __post_init__(self) -> None:
        """校验 node_id 非空"""
        if not self.node_id:
            raise ValueError("NodeRef.node_id 不能为空")

    def as_list(self) -> list:
        """序列化为 ComfyUI API 格式 [node_id, output_index]"""
        return [self.node_id, self.output_index]


@dataclass
class Node:
    """ComfyUI 节点 — node_id + class_type + inputs

    用 dataclass 替代裸 dict，让节点 ID 和连线引用有类型约束。
    inputs 中的引用值以 ComfyUI 原生 [node_id, output_index] 格式存储。

    Attributes:
        node_id: 节点唯一标识
        class_type: ComfyUI 节点类型（如 "KSampler"）
        inputs: 节点输入字典，值为标量或 [node_id, output_index] 引用
    """

    node_id: str
    class_type: str
    inputs: dict[str, Any] = field(default_factory=dict)

    def ref(self, output_index: int = 0) -> NodeRef:
        """创建指向本节点指定输出的 NodeRef"""
        return NodeRef(node_id=self.node_id, output_index=output_index)

    def set_input(self, key: str, value: Any) -> None:
        """设置输入值，自动将 NodeRef/Node 包装为 ComfyUI [node_id, output_index] 格式

        - NodeRef → 转换为 [node_id, output_index]
        - Node → 创建 ref(0) 后转换为 [node_id, 0]
        - 其他值（str/int/float/list）→ 原样存储
        """
        if isinstance(value, NodeRef):
            self.inputs[key] = value.as_list()
        elif isinstance(value, Node):
            self.inputs[key] = value.ref(0).as_list()
        else:
            self.inputs[key] = value

    def get_input(self, key: str) -> Any:
        """获取输入原始值（可能为标量或 [node_id, output_index] 引用）"""
        return self.inputs.get(key)

    def get_input_ref(self, key: str) -> NodeRef | None:
        """获取输入值并解析为 NodeRef，非引用值返回 None"""
        val = self.inputs.get(key)
        return _parse_ref(val)


def _parse_ref(val: Any) -> NodeRef | None:
    """解析 [node_id, output_index] 格式的引用，非引用值返回 None"""
    if not isinstance(val, list) or len(val) != 2:
        return None
    node_id, output_index = val
    if not isinstance(node_id, str) or not isinstance(output_index, int) or isinstance(output_index, bool):
        return None
    return NodeRef(node_id=node_id, output_index=output_index)


def _serialize_value(val: Any) -> Any:
    """将 NodeRef/Node 值序列化为 ComfyUI [node_id, output_index] 格式"""
    if isinstance(val, NodeRef):
        return val.as_list()
    if isinstance(val, Node):
        return val.ref(0).as_list()
    return val


@dataclass
class WorkflowGraph:
    """ComfyUI 工作流图 — 节点集合

    提供 add_node/find_by_class/to_dict/from_dict 等方法，
    支持类型安全的图操作和 ComfyUI JSON 序列化/反序列化。

    Attributes:
        nodes: 节点字典，key 为 node_id，value 为 Node 对象
    """

    nodes: dict[str, Node] = field(default_factory=dict)

    def add_node(self, node: Node) -> None:
        """添加节点，ID 冲突时 raise ValueError"""
        if node.node_id in self.nodes:
            raise ValueError(f"节点 ID 冲突: {node.node_id}")
        self.nodes[node.node_id] = node

    def get_node(self, node_id: str) -> Node | None:
        """按 ID 获取节点，不存在返回 None"""
        return self.nodes.get(node_id)

    def find_by_class(self, class_type: str) -> list[Node]:
        """查找指定 class_type 的所有节点"""
        return [node for node in self.nodes.values() if node.class_type == class_type]

    def find_first(self, class_type: str) -> Node | None:
        """查找指定 class_type 的第一个节点，不存在返回 None"""
        for node in self.nodes.values():
            if node.class_type == class_type:
                return node
        return None

    def resolve_ref(self, ref: NodeRef) -> Node | None:
        """解析 NodeRef 指向的节点，不存在返回 None"""
        return self.nodes.get(ref.node_id)

    def to_dict(self) -> dict:
        """序列化为 ComfyUI API 格式

        返回 {node_id: {"class_type": ..., "inputs": {...}}} 字典，
        inputs 中的 NodeRef/Node 值自动转换为 [node_id, output_index] 格式。
        """
        result: dict[str, dict] = {}
        for node_id, node in self.nodes.items():
            result[node_id] = {
                "class_type": node.class_type,
                "inputs": {k: _serialize_value(v) for k, v in node.inputs.items()},
            }
        return result

    @classmethod
    def from_dict(cls, data: dict) -> WorkflowGraph:
        """从 ComfyUI JSON 反序列化

        跳过以 _ 开头的 key（如 _meta），将剩余节点解析为 Node 对象。
        """
        graph = cls()
        for node_id, node_data in data.items():
            if node_id.startswith("_") or not isinstance(node_data, dict):
                continue
            class_type = node_data.get("class_type", "")
            inputs = dict(node_data.get("inputs", {}))
            graph.add_node(Node(node_id=node_id, class_type=class_type, inputs=inputs))
        return graph
