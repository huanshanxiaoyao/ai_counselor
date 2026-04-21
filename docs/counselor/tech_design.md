Project MindGraph 技术架构方案设计
1. 架构设计原则 (Design Principles)
隐私绝对隔离 (Privacy by Design)： 架构层面保障“阅后即焚”，原始对话数据不可在持久化层长时间驻留。

状态机驱动 (State-Driven)： 复杂心理学干预流派（CBT等）剥离大模型自由发散，由确定性的 LangGraph 状态图谱控制。

高可用兜底 (Resilience)： 面对 LLM 厂商 API 超时或宕机，具备降级模型或预设话术的平滑兜底能力。

2. 核心技术栈选型 (Tech Stack Recommendations)
主控框架： LangChain + LangGraph (用于构建多智能体与流派状态机)

后端服务： FastAPI (Python) (提供高性能、高并发的异步 API 接口)

大语言模型 (LLM)：

主推理模型： 逻辑能力强、上下文窗口大的模型 (如 Claude 3.5 Sonnet / GPT-4o / 智谱 GLM-4) —— 用于复杂认知干预。

快响应/总结模型： 速度快、成本低的模型 (如 豆包 Doubao-pro / Qwen-Turbo) —— 用于前置风控拦截、意图分类与结束时的摘要提炼。

数据库 (DB)：

会话缓存 (Short-term)： Redis (存储 LangGraph Checkpointer，会话结束后立即释放)。

长期记忆 (Long-term)： PostgreSQL (存储用户基础信息与结构化摘要) + Milvus / Pinecone (轻量级向量库，可选，用于后续复杂的成长日记语义检索)。

3. 系统三层逻辑架构 (System Architecture)
L1：接入网关与安全风控层 (Gateway & Security Layer)
所有终端请求的第一站，极速且轻量。

Crisis Detector (危机拦截器)： 使用轻量级 NLP 模型或正则词库。一旦命中了“自杀/自残/绝望”等高危意图，直接阻断该请求进入大模型集群，并在毫秒级返回预设的【危机干预热线与安抚卡片】。

Supervisor Agent (主控路由调度)： 分析用户的入口参数（Persona_ID），将请求精确转发至对应的 L2 流派子图谱引擎。

L2：图谱工作流与智能体层 (LangGraph Orchestration Layer)
业务的心脏，执行具体的心理学流派逻辑。

CBT_Graph (认知行为图谱)： 包含一组业务节点（Nodes）。

Greeting_Node: 结合长记忆动态生成开场白。

Mood_Check_Node: 提取情绪指数。

Intervention_Nodes: 包含苏格拉底提问、向下箭头技术等核心干预。

Fallback_Node: 异常处理与兜底节点。

Prompt Assembly Engine (提示词组装引擎)： 动态拉取当前 Node 对应的心理学方法论 JSON（我们之前提炼的结构）和用户历史记忆，拼接送入大模型。

L3：记忆与“阅后即焚”持久化层 (Memory & Burn Pipeline)
Checkpointer (临时记忆快照)： 挂载在 Redis 上。用户聊天的每一句话（messages 数组）都会保存在这里，用于多轮对话的断点续传。

The Burn Engine (焚毁引擎)： 监听 Session_End 事件触发的核心微服务。

Summary Storage (摘要归档)： 结构化的 JSON 摘要存储。

4. 核心数据结构 (Data Schema)
在 LangGraph 中，一切流转皆基于 State。以下是核心状态字典定义：

Python
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages

class MindGraphState(TypedDict):
    # --- 基础对话数据 ---
    session_id: str
    user_id: str
    messages: Annotated[list, add_messages]  # 本次对话的全量消息流 (阅后即焚对象)
    
    # --- 路由与状态控制 ---
    persona_id: str         # 选择的角色 (决定了 Prompt 的语气)
    therapy_mode: str       # 疗法流派 (如 "CBT", "Psychoanalysis")
    current_phase: str      # 图谱流转节点 (如 "greeting", "cognitive_restructuring")
    crisis_flag: bool       # 熔断标志位
    
    # --- 长短期记忆数据 ---
    last_summary: str       # 上次会话的摘要 (由 L3 层注入)
    current_homework: str   # 本次会话产生的行动计划 (结束时写入)
    mood_score: int         # 本次对话的情绪打分 (0-10)
5. 关键技术链路详解 (Key Technical Pipelines)
5.1 阅后即焚数据流 (The "Burn" Pipeline)
这是本产品的信任护城河，必须保证原子性操作（全有或全无）。

触发条件： 用户点击“结束对话” 或 闲置超时。

异步总结任务： 系统将 Redis 中当前 session_id 的全量 messages 投递给【快响应总结模型】，生成结构化摘要。

前端确认机制： 生成的摘要推给前端用户，此时 Redis 中的 messages 仍保留（设置较短的 TTL 过期时间）。

硬删除执行： - 无论用户选择“保存”、“修改后保存”还是“彻底销毁”。

只要前端返回确认指令，后端立即执行 redis.delete(session_id)。

仅将用户确认后的摘要内容 INSERT 到 PostgreSQL 的 user_summary 表中。

5.2 记忆动态注入与“自然开场” (Dynamic Memory Injection)
为了实现“不生硬地查作业”，我们需要拦截系统的第一条回复。

启动时： Supervisor 读取 PostgreSQL，查出该用户最近一次的 last_summary。

注入 System Prompt：

Plaintext
[Persona设定]: 你是温暖的知心学姐...
[系统时间]: 今天是周五晚上...
[历史档案]: 用户上次感到焦虑，你们约定的微小行动是"下班后去花店买一束花"。
[开场指令]: 请根据上述信息和时间打招呼。必须将提及"买花"这件事自然地融于日常问候中，绝不能像质问或查岗。如果用户没做，你需要表现出完全的接纳。
生成输出： 保证角色的“人味”和连贯性。

5.3 应对大模型超时的容错降级策略 (Fallback Strategy)
AI 产品的死穴是“转圈圈后报错”。在 LangGraph 中，我们使用双重图节点兜底：

当 Intervention_Node (调用复杂大模型，设置 timeout=8s) 发生超时或 API 返回 502 时。

捕获异常，State 不报错退出，而是触发图谱的 Conditional_Edge，路由至 Fallback_Node。

Fallback_Node 挂载快速/本地小模型，或者直接输出预设话术：“(系统稍有卡顿) 刚才聊到那里，你的感受确实很深刻，你愿意再多跟我描述一点当时的细节吗？”

效果： 用一句万能的“共情+追问”话术，为系统争取时间，保证对话不断网。

6. 后续扩展规划 (Future Extensibility)
横向流派扩展： 由于使用了 Supervisor Agent 路由层，未来增加“精神分析”流派，只需开发一个独立的 Psychoanalysis_Graph，并注册到 Supervisor 的路由表中，完全无需改动现有的 CBT 代码，符合开闭原则（OCP）。

多模型竞合： 通过 LangChain 的统一接口，可以随时切换底层的 LLM 供应商，寻找成本和效果的最佳平衡点。
