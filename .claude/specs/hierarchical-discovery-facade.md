---
title: Hierarchical discovery facade — packages → modules → usage
status: approved
created: 2026-07-21
revised: 2026-07-21
grilled: false
philosophy: okf-context-injection
---

# Hierarchical discovery facade — packages → modules → usage

## Summary

重构 molmcp 面向 agent 的 **MCP facade**，对齐 **Open Knowledge Format（OKF）式「内容即上下文」**：

1. **Codegraph = 知识索引**（像磁盘上的 concept 树 / 链接图），不是给 agent 的主交互模型。
2. **Facade = 按层打开知识页并注入上下文**——返回的是可读叙事块（summary / outline / open 正文），**不是**「排序分 + top-k 赌对」。
3. **最终价值**是通过 molmcp 把选定知识 **注入 LLM 上下文**（ContextPack / markdown pages），让模型自己读懂 molpack 管 pack、molpy.io 管读写。

默认发现路径从「扁平 FTS + 传统排序」改为 **分级打开 + 内容注入**：

```text
L0  packages()   → 注入「包目录页」（每包一段描述，模型自己选）
L1  outline()    → 注入「模块目录页」（molpy 下 io/core/…）
L2  open(ref)    → 注入「符号正文页」（签名+doc+examples+tests）
L*  compose()    → 把多页装订成有预算的 ContextPack（explore 的正名）
```

`search` 降为 **索引辅助**（在目录内按名查找），不是能力发现的主路径；ranking 只服务「一页放不下时的截断优先级」，**不得替代把正确页注入上下文**。

引擎层（`DiscoveryQuery.outline` / `examples_of` / `tests_of`）已具备索引能力；本 spec 改 facade + collection 对外契约，不重写 graph schema，不把包名 hardcode 进 molexp。

与既有工作：

- **修正** `retrieval-first-discovery` 的表述：检索/索引仍必要，但 **交付物是上下文页，不是排行榜**；call graph 仅作 open 页内的可选链接。
- 对齐 `molmcp-vnext`：discovery ≠ execution；仅 `executable=true` 可 bind。
- 收敛今日 `guide/search/describe/usage/explore` 到 OKF 式「目录 → 打开 → 装订」。

## Domain basis

### OKF 类比（molexp workspace）

OKF Concept 是目录：`meta.yaml`（类型）+ `index.md`（叙事）+ markdown 链接（边）。
**知识图 = 可读文本与链接**，不是独立的 rank API。Agent「懂」一个概念的方式是 **读 index**，不是看 edge weight。

molmcp 应对代码生态做同构：

| OKF | molmcp 知识面 |
|---|---|
| concept 目录 | source / package / module |
| `meta.yaml` type | kind + executable 标记 |
| `index.md` 叙事 | package/module summary + symbol doc/signature |
| markdown 链接 out_edges | contains / examples / tests / RESOLVED relations（**渲染进正文**，不是排序分） |
| Bundle 读出上下文 | ContextPack / open 页注入 |

### 为何不用传统排序当主干

- Top-k ranking 是 **压缩损失**：正确 API 不在 top-k 即静默失败（e2e 乱 pack 即此）。
- LLM 的优势是 **读中等长度目录并选择**，不是吃黑盒分数。
- Codegraph 的价值是 **可寻址索引**（打开哪一页、页上链到哪），不是 pagerank 替代理解。

### Codegraph 诚实边界

| 索引能稳定给的 | 不能假装有的 |
|---|---|
| package/module 树 | 动态属性、跨语言完整调用 |
| 签名/docstring | 每个符号都有 example 节点 |
| RESOLVED 边 | HEURISTIC 当真理 |
| status=ok 的 source | index error 的 source |

空洞必须在注入页上显式写出（`examples: []` + `coverage`）。

## Design

### 0. 北极星：Context Injection Law

```text
Agent 不消费「排序结果列表当真理」；
Agent 消费「molmcp 装订好的知识页 / ContextPack」。
Codegraph 只回答：有哪些页、页与页如何链接、如何按路径打开。
```

任何工具若只返回 `[{score, title}]` 而无足够叙事，视为 **未完成 facade**。

### 1. 目标 agent 回路（权威路径 = 打开目录）

```text
task
  │
  ├─► packages()     # 注入 L0 目录页：全包 summary（模型读后自选）
  │
  ├─► outline(source, path?)
  │                  # 注入 L1 目录页：模块树 + 模块 summary
  │
  ├─► open(ref)      # 注入 L2 正文页：签名/doc/examples/tests/链接
  │
  └─► compose(task | refs[], budget)
                     # 装订多页 → ContextPack（有字符预算，可截断但标 omitted）
```

**索引辅助（非权威）**：`search(query, source=, kind=)` 仅在已知目录内找 ref 字符串；结果项必须带足够 summary 以便决定是否 `open`。
**捷径**：`suggest(task)` 可建议「先读哪几个 package 页」，不得替代 packages/outline/open。

### 2. Facade 工具表（最终 MCP 面）

统一前缀 `molcrafts_*`，全部 read-only。每个成功响应优先是 **可直接塞进 prompt 的 `markdown` 页**（OKF `index.md` 精神），并附带结构化 `data` 供程序用。

Envelope：`ok` / `code` / `error` / `markdown` / `data`。

| Tool | 层级 | 注入什么 |
|---|---|---|
| `molcrafts_packages` | L0 目录页 | 每个 source 一段：名称、状态、**summary 正文**、freshness；error source 也写出失败原因 |
| `molcrafts_outline` | L1 目录页 | 选定 source（+path）下模块列表 + **module summary**；可选浅层 exported symbols |
| `molcrafts_open` | L2 正文页 | 一个 ref 的完整知识页：签名、doc、examples、tests、RESOLVED 链接、executable handoff |
| `molcrafts_compose` | 装订 | 给定 task 和/或 refs[] + `budget_chars` → ContextPack（多页装订；截断写 `omitted`） |
| `molcrafts_search` | 索引辅助 | 在 source/kind/path 范围内找 ref；每条 hit 必须带 summary 片段 |
| `molcrafts_suggest` | 捷径 | 任务 → 建议先读哪些 package 页（live inventory only） |
| `molcrafts_info` | 运维 | 健康/配置；不是主发现路径 |
| `molcrafts_refresh` | 运维 | 可选 re-index |

**兼容（一个 minor）**：`describe`/`usage`→`open`；`guide`→`suggest`；`explore`→`compose`（同语义增强）。文档只教 packages → outline → open → compose。

**明确不做**：

- 把 ranking score 当主交付物。
- 任意图查询语言。
- molexp hardcode 包菜单。
- HEURISTIC 调用边当默认正文链接。

### 3. 响应契约（关键字段）

**Package card（L0）**

```json
{
  "name": "molcrafts-molpack",
  "status": "ok",
  "spec": "pkg:molcrafts_molpack",
  "freshness": "fresh",
  "summary": "Packmol-grade molecular packing…",
  "summary_source": "package_docstring",
  "module_count": 12,
  "role_hint": "packing",
  "role_hint_source": "name_fragment|summary_keyword|null",
  "warnings": []
}
```

`status != ok` 的包仍列出，带 `error`，**禁止**从 search 里默默消失。

**Outline module（L1）**

```json
{
  "qualname": "molpy.io",
  "kind": "package|module",
  "summary": "Unified interface for molecular file I/O.",
  "file": "molpy/io/__init__.py",
  "top_symbols": [{"qualname": "…", "kind": "function", "signature": "…", "summary": "…"}]
}
```

**Open（L3）** — miss：

```json
{"ok": false, "code": "SYMBOL_NOT_FOUND", "ref": "…", "hint": "packages → outline → search with source="}
```

### 4. 实现放置（Reuse）

| 能力 | 复用 | 动作 |
|---|---|---|
| 模块树 | `DiscoveryQuery.outline` | **reuse** — collection 层包一层 multi-source 路由 |
| 符号精读 + examples/tests | `CollectionIndex.describe` / `_related_nodes` | **reuse** — 统一为 `open` |
| 跨源 search | `CollectionIndex.search` | **reuse** — 加 source/kind/path 过滤 |
| 包 summary | package 节点 summary/docstring via query | **generalize** — packages() 批量取每个 source 的根 package 节点 |
| guide/suggest | `molmcp/guide.py` | **reuse** — 改名语义为 suggest；role 仅 hint |
| 旧 DiscoveryProvider 六工具 | 文档遗留 | **不复活**旧名字；能力并入新 facade |

**推荐模块**：

- `molmcp/collection/browse.py`（或 `facade.py`）— packages / outline / open 的纯逻辑（无 FastMCP）。
- `molmcp/mcp_provider.py` — 只注册工具。
- `molmcp/guide.py` — suggest 专用。
- 测试：`tests/test_mcp_vnext.py` 改为新工具集；`tests/test_browse.py` 覆盖分级契约。

### 5. Server instructions（写死教法）

```text
MolMCP injects knowledge pages into your context (OKF-style). Do not treat scores as truth.

1. molcrafts_packages — read the package directory page; choose sources by summary
2. molcrafts_outline(source=…, path?=) — read the module directory page
3. molcrafts_open(ref) — inject the symbol page before writing code
4. molcrafts_compose(task|refs, budget) — when you need a multi-page pack
5. Only executable=true may be handed to Molexp as a capability
search/suggest are index helpers, not substitutes for opening pages
```

### 5.1 molexp / plan 消费

- Grounding 与 codegen：**注入** packages 页 + 相关 outline/open 页，而不是只塞 capability_id 列表。
- Catalog 可视为 packages/open 的 **摘录**，完整证据仍以 molmcp 页为准。

### 6. molexp 消费方（同 spec 的对接要求，实现可分 PR）

- `mcp_capabilities.fetch_*`：优先 `packages` + 对 prefer sources 的 `outline`/`search`；**删除**任何包名硬编码列表。
- Plan codegen system prompt：要求「先 packages/outline 再 open」。
- 不在 molexp 复制 role 表。

### 7. 数据质量配套（facade 可工作的前置）

Facade 不修 analyzer，但 **acceptance 要求可观测**：

- `packages` 对 status=error 的 source 必须可见。
- `open` 对 examples/tests 为空时返回明确 `coverage: {examples: 0, tests: 0}`。
- 文档列出：修 index 失败、补 example 边、registry executable 为 **后续轨道**（见 Out of scope）。

## Files to create or modify

**Create**

- `src/molmcp/collection/browse.py` — packages / outline / open 实现
- `tests/test_browse.py` — 分级契约单测（可用 fixture_pkg + 可选 live molpy）
- `docs/concepts/hierarchical-discovery.md` — agent 回路说明（可在实现 PR 写）

**Modify**

- `src/molmcp/mcp_provider.py` — 注册新工具 + alias
- `src/molmcp/collection/index.py` — 过滤参数；必要时 thin wrappers
- `src/molmcp/guide.py` — 定位为 suggest
- `src/molmcp/server.py` — instructions
- `src/molmcp/__init__.py` / README / quickstart — 文档面
- `tests/test_mcp_vnext.py` — 核心工具集与 envelope
- `tests/test_guide.py` — 对齐 suggest 命名
- molexp（可选 follow-up PR）：`mcp_capabilities.py`、plan prompts

## Tasks

1. **Spec-lock envelope** — 固定 ok/code/error + packages/outline/open JSON shape 的 golden fixtures。
2. **Implement `collection.browse.packages`** — 每 source 一张卡；summary 来自根 package 节点；error source 保留。
3. **Implement `collection.browse.outline`** — 路由到对应 source 的 `DiscoveryQuery.outline(path)`；跨 source 拒绝或要求 source。
4. **Implement `collection.browse.open`** — 合并 describe+usage；coverage 字段；RESOLVED-only relations 默认。
5. **Extend search filters** — `source` / `kind` / `path` 前缀过滤。
6. **Wire MCP tools + aliases** — packages, outline, open, search, suggest, info, explore；describe/usage/guide alias。
7. **Update instructions + README/quickstart** — 只教分级路径。
8. **Tests** — vnext 工具集；browse 单测；guide→suggest 兼容。
9. **molexp follow-up（可拆 PR）** — grounding 改吃 packages/outline；删 hardcode 残留。

## Testing strategy

- **Unit**：fixture_pkg 上 packages 返回 summary；outline 模块数；open miss → SYMBOL_NOT_FOUND。
- **Contract**：MCP list_tools 含新集合；describe/usage 仍可用（alias）。
- **Integration（optional live）**：`pkg:molpy` outline 含 `molpy.io` 且 summary 非空（skip if molpy 未装）。
- **Non-goals as tests**：不要求 CoarseGrain 必有 examples；不要求 registry 非空。

## UI verification

（无 UI。）

## Out of scope

- 重写 codegraph schema / 新语言 analyzer。
- 向量语义检索。
- 自动修 molpack index 失败根因（只要求 facade 暴露 status=error）。
- 为每个 API 补 example 节点的内容工程。
- 把 call graph 重新加入 ranking（违反 retrieval-first-discovery）。
- molexp PlanMode 流水线重构（仅对接 facade；sequential task build 已有）。

## Open questions

1. `role_hint` 是否保留？**建议保留但标 `role_hint_source`，且允许 null**——权威是 summary，hint 仅加速。
2. `outline` 默认是否带 `top_symbols`？**建议默认带 exported、limit=15**，大包用 path 收窄。
3. Alias 保留几个 minor version？**建议至少一个 minor，文档标 deprecated。**

## Acceptance pointer

见同目录 `hierarchical-discovery-facade.acceptance.md`。
