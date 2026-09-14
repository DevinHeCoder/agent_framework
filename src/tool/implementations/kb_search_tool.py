"""检索工具：对内置知识库做关键词匹配检索（mock 实现，可替换为向量检索后端）。

当前实现：把 query 按空白/标点切词，对知识库文档按词命中数打分，
返回 top_k 结果；结果携带 "source": "mock" 标记。
"""
import re
from typing import List

from src.tool.base import BaseTool, ToolSchema
from src.tool.registry import tool_registry

# 内置演示知识库（doc_id + 标题 + 正文）
_DEFAULT_KB: List[dict] = [
    {"doc_id": "doc-1", "title": "Agent 框架简介",
     "content": "轻量智能 Agent 工具编排框架自研 ReAct 循环，支持工具注册、参数校验、会话记忆与失败兜底。"},
    {"doc_id": "doc-2", "title": "可插拔工具注册中心",
     "content": "工具注册中心通过注册表统一管理天气、检索、计算器、时间等工具，支持一行注册即生效。"},
    {"doc_id": "doc-3", "title": "双缓存记忆机制",
     "content": "记忆层采用短时内存缓存与长时 Redis 持久化的冷热分层，支持多轮会话状态恢复。"},
    {"doc_id": "doc-4", "title": "任务规划与 ReAct",
     "content": "Agent 由规划器拆解任务为多步，ReAct 循环每步选择工具执行，直至完成或达到最大轮次。"},
    {"doc_id": "doc-5", "title": "异常重试与兜底",
     "content": "工具调用失败自动重试，参数错误回喂 LLM 修正，无法修复时优雅降级给出兜底答案。"},
]


def _segments(text: str) -> List[str]:
    """切分文本为检索单元：英文单词 + 中文二元组（bigram）。

    中文不按空格分词，若用正则 `\\W` 切分会把整句连成一个 token，
    导致无法命中；故中文连续块按 bigram（相邻两字）切分，
    兼顾命中率与区分度。
    """
    out: List[str] = []
    for token in re.split(r"\s+", text):
        # 英文 / 数字词
        for eng in re.findall(r"[A-Za-z0-9_]+", token):
            out.append(eng.lower())
        # 中文连续块
        for zh in re.findall(r"[\u4e00-\u9fff]+", token):
            if len(zh) == 1:
                out.append(zh)
            else:
                out.extend(zh[i:i + 2] for i in range(len(zh) - 1))
    return out


@tool_registry.register("kb_search")
class KbSearchTool(BaseTool):
    """知识库关键词检索工具（mock 实现）。"""

    def __init__(self, top_k: int = 3, knowledge_base: List[dict] | None = None):
        self.top_k = top_k
        self._kb = knowledge_base if knowledge_base is not None else _DEFAULT_KB

    @property
    def tool_schema(self) -> ToolSchema:
        return ToolSchema(
            name="kb_search",
            description="检索内置知识库，返回与查询最相关的文档片段（含 doc_id 与内容）。",
            parameters={
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索查询语句，如 '工具注册中心是什么'",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果条数，默认取工具配置（1-10）",
                        "minimum": 1,
                        "maximum": 10,
                    },
                },
            },
        )

    def run(self, query: str, top_k: int | None = None) -> dict:
        k = top_k or self.top_k
        query_segments = _segments(query)
        if not query_segments:
            return {"query": query, "results": [], "source": "mock"}

        scored = []
        for doc in self._kb:
            blob = f"{doc['title']} {doc['content']}"
            doc_segments = set(_segments(blob))
            hits = sum(1 for s in query_segments if s in doc_segments)
            if hits > 0:
                scored.append((hits, doc))

        scored.sort(key=lambda x: (-x[0], x[1]["doc_id"]))
        results = [
            {"doc_id": doc["doc_id"], "title": doc["title"], "content": doc["content"], "score": score}
            for score, doc in scored[:k]
        ]
        return {"query": query, "results": results, "source": "mock"}
