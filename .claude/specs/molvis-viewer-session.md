---
title: MolVis viewer session — live-stage exec primitives + selection feedback
status: code-complete
created: 2026-08-02
revised: 2026-08-02
grilled: false
---

# MolVis viewer session — live-stage exec primitives + selection feedback

## Summary

在 molmcp 中新增 **first-party `molvis` Provider**:在 `molmcp serve` 进程内维持活着的 MolVis `Stage` 会话,agent 通过 **`exec` 原语直接写 molvis / molpy Python 代码**操作它——`stage.draw_frame(mol)`、`stage.get_selected()`、`stage.clear()`,即 molvis 自己的公开 API。

**设计铁律:**

1. **molmcp 不发明任何 API。** 无具名包装工具(复合或 1:1 皆禁),无 agent-facing 的 send_cmd/JSON-RPC 面——agent 写的每一行都是 molpy / molvis 的公开 Python API,wire 协议留作 molvis 内部实现细节。
2. **严禁环境变量;不设权限/门控机制。** 5 个工具全部直接可用;信任模型 = 本地、用户自己启动的 serve、同进程 workbench(与 Jupyter kernel 同级),spec 不引入任何 opt-in 开关。
3. 工具面共 5 个原语:`open` / `close` / `list_sessions` / `exec` / `poll_events`。molvis/molpy 新增任何 API,molmcp **零改动**。

北极星对话(人工验收,非 in-tree 产品测试):

1. 用户:「我要创建一个 aspirin」→ agent `open`,然后 `exec`:

   ```python
   import molpy as mp
   mol = mp.parser.parse_molecule("CC(=O)Oc1ccccc1C(=O)O")
   mol, _ = mp.Conformer(seed=42).generate(mol)
   stage.draw_frame(mol)
   ```

2. 用户在 canvas 上点选一部分结构。
3. 用户:「把这个换成 …」→ agent `poll_events` 见 `selection_changed`,`exec`(命名空间持久,`mol` 还活着):

   ```python
   sel = stage.get_selected()      # 独立子 Frame,自带元素/坐标
   # … molpy 编辑 mol …
   stage.clear(); stage.draw_frame(mol)   # 盖章语义:刷新必先 clear
   ```

**E2E / 剧本 harness 不进 molmcp 或 molvis 产品树**;单独放在 out-of-tree 目录(见 Testing)。本 spec 只交付 molmcp 侧 provider + agent 学习路径 + in-tree 单元测试。

## Domain basis

### 为什么要 Provider(对照四条件)

| 条件 | 本 Provider |
|------|-------------|
| 稳定签名 | 5 个原语,签名不随 molvis/molpy API 演化;词汇表在上游 |
| 读/写 | 读:list_sessions / poll_events;写:open / close / exec |
| 每会话高频 | 可视化联控是「当前任务 dashboard」级 |
| 单次短答 | exec 返回单次执行结果;poll 返回事件增量;多步流程 = agent 多次 exec |

Provider 解决的是 **discovery 看不见的 runtime**:活着的 Stage、跨 MCP 调用存活的 Python 对象(`mol`)、事件流。API 语义不在 provider 里——见「Agent 如何学会写 exec 代码」。

**为什么 exec 而非 JSON-RPC call:** MCP 与 Stage 同进程,而 agent 经 Bash 起的 Python 是另一进程,摸不到 serve 里的 Stage;没有进程内执行入口,「molpy 建结构 → 画」的回路根本闭合不了(frame 编码无处可跑)。exec 就是把 spec 一直假设的「同进程脚本环境」真正交付出来;顺带,直接用 molvis Python API 让 agent 免碰 wire 编码,选区读回 `get_selected()` 直接是带元素坐标的子 Frame,前几版纠结的 id 映射契约整体消失。

### 已有能力(reuse,不重做;均已对源码核实)

| 能力 | 位置 | 决策 |
|------|------|------|
| Provider 协议 + entry point | `provider.py`, `pyproject` `molmcp.providers` | **reuse** — 注册 `molvis` |
| 会话注册表 | molvis `Stage`(=`Molvis`)/ `session_summary()` / `close()` | **reuse** — lazy import |
| 操作面 | molvis 公开 Python API(`draw_frame` 接受 Atomistic、`clear`、`get_selected` 返回独立子 Frame、`camera.fit`、`send_cmd` 兜底),docstring 完备 | **reuse** — agent 在 exec 里直接调,provider 零包装 |
| 建/改分子 | molpy `parse_molecule` / `Conformer.generate`(返回新对象)/ `Atomistic` 图编辑 | **reuse** — agent 在 exec 里直接调 |
| 上行事件 | molvis `EventBus`(WS 线程 dispatch,线程安全)、`event.selection_changed` 等 notification | **reuse** — journal 源,payload 原样 |
| 连接状态 | molvis `connected` / `connection_url` | **reuse** — open 返回 / get 状态可 exec 查 |
| 测试传输 | molvis `Molvis.from_inprocess` + `transport/inprocess`(无浏览器,走真 RPC 路径) | **reuse** — in-tree 联调测试 |
| Discovery 索引 | `discovery/analyzers/`(python);`guide.py:71` 已映射 `molvis → visualization` | **reuse** — 学习路径主干 |

### 架构:一个会话,两个表面,两个意志(四方)

```text
        人操作                            agent 控制
    (意志:看着改)                    (意志:按对话改)
        │ 点选 / 模式 / 查看                │ MCP 5 原语
        ▼                                  ▼
   canvas 显示    ◄═════ WS ═════►   代码操作(Python 会话)
   molvis viewer(浏览器页面)         mol(molpy,结构真相)
   渲染 mol 的投影 + 承接交互          + stage(molvis controller)
   经 connection_url 打开             一切领域调用只发生在这里
```

四方与职责:

| 方 | 表面 | 职责 | 由谁实现 |
|---|------|------|----------|
| 人操作 | 浏览器 UI | 观看、点选、模式切换——表达「改哪里」 | 用户 |
| canvas 显示 | 浏览器页面 | 渲染投影、承接交互、上行 `event.*` | molvis 前端 |
| 代码操作 | molmcp serve 进程内 Python 会话 | 持有 `mol` + `stage`;一切 molpy/molvis 调用 | 上游公开 API + session namespace |
| agent 控制 | MCP | 会话生命周期、注入代码、观察事件、决策 | molmcp 5 原语 |

四条边,各归其主:

1. **人 ↔ canvas**(交互契约)——molvis 前端负责,molmcp 不可见。
2. **canvas ↔ 代码操作**(投影契约,WS/JSON-RPC)——molvis 内部实现细节,molmcp 不碰、不暴露。
3. **agent ↔ 代码操作**(工作台契约)——molmcp 的全部职责:exec 注入 + namespace 持久 + journal 拉取。
4. **人 ↔ agent**(对话)——自然语言,在 molmcp 之外(host 层)。

推论:

- 「同进程」约束只作用于边 3:代码操作层(stage + namespace)与 MCP server 必须同进程,否则 agent 摸不到活对象;画布从来就在浏览器里。
- **两个意志异步汇合**:人经边 1→2 改选区,agent 经 `poll_events`(边 3)看见;agent 经边 3 改 `mol` 并重画,人经边 2→1 看见。互不阻塞,汇合点是会话状态(`mol` + journal)。
- **agent 控制 ≠ 代码操作**:agent 的工具面只管「会话在不在、代码进得去、事件出得来」;真正干活的是代码,领域词汇只存在于代码层,来自 molpy/molvis。
- `exec` 无沙箱、无隔离——本地 workbench 信任模型(与 Jupyter kernel 同级),docs 一句话说明,不做权限设计。附着外部已启动的 Python/浏览器会话不在本设计内(见 Out of scope)。
- Provider 对 API 语义**零中介**:不校验 agent 代码、不映射任何东西。盖章语义(`draw_frame` 不清屏)、刷新=`clear`+`draw_frame`、`get_selected` 的返回形态,全部是 **molvis 的契约**,agent 经 discovery 学;异常原样转成结构化 traceback 返回。

### molvis 侧配套缺口(依赖清单,molvis 另 spec,molmcp 不代偿)

agent 经 exec 直接调 molvis Python 时,以下不便之处的修复属于 **molvis**;molmcp 不得以包装/映射代偿(零词汇铁律):

| # | 缺口 | 证据 | molvis 侧解(单一职责) | 阻塞面 |
|---|------|------|------------------------|--------|
| 1 | 选区 → 源结构行号无公开对应 | 选区 id 是前端 `atomId`(`router.ts:942`);draw 返回的 id 私藏于 `_atom_ids`(`scene.py:264`);`get_selected()` 子 Frame 无回溯列 | 三选一:**钉契约**(测试+docstring 固化「clear 后单次 draw,选区 id ≡ 绘制行号」,零新 API,推荐)/ `get_selected()` 加源行号列 / 公开 `stage.atom_ids` | **阻塞北极星第 3 步「编辑选中」**;整分子替换不受影响 |
| 2 | 未连接时 draw 系阻塞 ~10s 后 TimeoutError | `cli.py:127` | 专用 `NotConnectedError`(携带 connection_url)立即抛 | 体验;agent 可先查 `stage.connected` 过渡(guide 教) |
| 3 | server 进程内构造行为未固化 | `runtime.py` 有 HEADLESS 检测但无「serve 进程」回归 | 回归测试:无显示环境只起 WS + 返 URL,不弹浏览器、不阻塞构造 | 实现时验证;预期已满足 |
| 4 | EventBus 无通配订阅 | `events.py dispatch` 仅按精确名分发,无 `on("*")` | molvis 加通配订阅;在此之前 journal 只能列举已知事件集(`selection_changed`/`mode_changed`/`frame_changed`/`hello_state`)——这是 provider 中唯一被迫存在的 molvis 词汇,molvis 补通配后删除 | Design §4「不挑选」暂降级为「列举已知集」 |

事件历史**不在**此列——EventBus 只缓存最新状态,历史正是 molmcp journal 的职责。

## Design

### 1. 组件

```text
src/molmcp/providers/molvis/
  __init__.py          # export MolvisProvider
  provider.py          # 5 个 MCP tools
  session.py           # SessionStore + ViewerSession + namespace + journal(MCP-free)
```

- `session.py` **零 FastMCP**,便于单测。
- `provider.py` lazy `import molvis`;缺依赖时 `register` 跳过或 tool 返回结构化错误(对齐 molq/molexp)。molpy 由 agent 代码自己 import,provider 不 import。
- 测试经 SessionStore 注入 stage factory(`Molvis.from_inprocess` 或 fake);工具签名不暴露测试参数。

### 2. Session 模型

```text
ViewerSession:
  session_id: str          # = Stage.name
  stage: molvis.Stage
  namespace: dict          # exec 的持久 globals;open 时创建并预绑定 stage,close 时丢弃
  journal: Journal         # 有界 ring buffer,锁保护(EventBus 从 WS 线程 dispatch)
  created_at / meta
```

- `open`:`Stage(name=session_id)`(或生成 id);**同名 session 已存在 → 结构化错误**,不 attach。
- `close`:`stage.close()` + 丢弃命名空间 + 从 store 移除。
- 进程内单例 store(provider 实例字段即可;测试可注入)。

### 3. Tool 面(namespace `molvis` → `molvis_*`,共 5 个,全部直接可用)

| Tool | 语义 |
|------|------|
| `open(session_id?=None)` | `Stage(name=…)` + 建命名空间(预绑定 `stage`);返回 `{session_id, connection_url}`;撞名报错 |
| `close(session_id)` | `stage.close()` + 丢弃命名空间 + store 移除 |
| `list_sessions()` | `Stage.session_summary()` 原样 |
| `exec(session_id, code)` | 在 session 命名空间执行 Python(REPL 语义);返回 `{stdout, value_repr, error?}` |
| `poll_events(session_id, since=0, limit=50)` | journal 增量 `{events, next_cursor, truncated}`;payload 原样 |

`exec` 的执行契约(通用 REPL 机械,零 molvis 知识):

- globals = session 命名空间(跨调用持久);`stage` 预绑定;import 无限制(serve 环境里装了什么就能用什么)。
- 返回:捕获的 `stdout` + 末表达式的 `repr`(REPL 语义);异常 → `{type, message, traceback}` 结构化返回,不吞。
- 输出上限(如 32 KB)截断并标 `truncated`,防止大对象 repr 冲爆上下文。
- 阻塞风险如实文档化:代码跑在 server 工作线程,`stage.wait()` 之类可长阻塞;超时上报但无法强杀(Python 线程语义),与 Jupyter 同性质。

**明确不做的 tool:** 任何具名包装(`show_smiles` / `draw` / `call` 等,历版全部否决)、agent-facing send_cmd/JSON-RPC 面(exec 里 `stage.send_cmd` 天然可用,但**不进教学路径**)、任何 env 开关或权限门控。

### 4. 事件 journal(唯一的"加工":pull 化)

- 订阅 stage 全部 `event.*` notification(现有集:`selection_changed` / `mode_changed` / `frame_changed` / `hello_state`;**不挑选**——molvis 加事件,journal 自动收)。
- **EventBus 从 WS 线程 dispatch**:append 与 `poll_events` 读取共用一把锁;cursor 单调性在锁内维护。
- 每条:`{cursor, type, ts, payload}`;payload **原样**,不映射、不摘要。
- ring buffer 已淘汰早于 `since` 的事件时返回 `truncated: true`。
- MCP **默认 pull**;不依赖 host 支持 notification。(agent 也可在 exec 里自设 `stage.on(...)` 监听——journal 只是免布置的默认通道。)

### 5. Agent 如何学会写 exec 代码(学习路径)

**主干 — discovery(molmcp 的本行):** 把 molvis 纳入 discovery source inventory(`guide.py:71` 已有 `molvis → visualization` 角色位)。语义全在上游 docstring 里,已核实:`draw_frame` 盖章语义与「只有 `clear` 全清」(drawing mixin docstring)、`get_selected` 返回独立子 Frame(selection mixin docstring)、molpy `Conformer.generate` 返回新对象。agent:`molcrafts_search("draw_frame")` → `molcrafts_open(ref)` 注入真契约页。**molmcp 不复述任何一条。**

**guide 回路页(本 spec 唯一新写的知识):** 一页教**回路**而非 API——Summary 里那两段 exec 代码就是全部内容骨架:建 → 画;读选区 → 改 → clear → 重画;命名空间持久所以 `mol` 不用重建。每个 API 的真相指回 discovery。该页**禁止**演变成 API 参考手册。

分工一句话:**每个 API 怎么用 = molpy/molvis docstring 的责任;怎么围成回路 = guide 一页;provider 代码里的领域知识 = 0 行。**

### 6. 文档

- `docs/concepts/provider-design.md`:molvis workbench 条目 + 「零词汇 / exec 原语」原则 + 同进程信任模型一句话。
- guide 回路页(见 §5)。
- **不**把 e2e 剧本写进 molvis 包 docs 当产品 example(剧本在 out-of-tree harness)。

## Files

| Path | Action |
|------|--------|
| `src/molmcp/providers/molvis/__init__.py` | create |
| `src/molmcp/providers/molvis/session.py` | create — SessionStore, ViewerSession(namespace), journal(锁保护) |
| `src/molmcp/providers/molvis/provider.py` | create — 5 tools + exec REPL 机械 |
| `pyproject.toml` | entry point `molvis = molmcp.providers.molvis:MolvisProvider` |
| `docs/concepts/provider-design.md` | molvis workbench section |
| guide 回路页(`docs/guides/` 或 guide.py 注入,按现有 guide 机制落位) | create |
| `tests/providers/test_molvis.py` | unit tests(fake stage + in-process transport) |
| `tests/providers/test_molvis_session.py` | session/namespace/journal 纯逻辑(含跨线程 append) |

Out-of-tree(**本仓库不创建**,仅约定路径供后续人工/CI 外挂):

| Path | Role |
|------|------|
| `../molvis-agent-e2e/`(与 molmcp 同级 sibling,名称可调) | 人工/半自动 e2e:aspirin 对话剧本、可选真实浏览器 |

## Tasks

- [x] 1. **Add** `providers/molvis/session.py` — `ViewerSession`(含持久 namespace)、锁保护 ring-buffer journal(cursor 单调 + truncated)、`SessionStore` open/get/close/list(撞名报错;stage factory 可注入)。
- [x] 2. **Add** `providers/molvis/provider.py` — 5 tools;exec REPL 机械(stdout 捕获、末表达式 repr、结构化 traceback、输出截断);lazy import;缺依赖失败形态稳定。
- [x] 3. **Wire** entry point in `pyproject.toml` + package export。
- [x] 4. **Subscribe** journal 到 stage 已知 `event.*` 集(WS 线程 append 上锁,payload 原样;通配订阅待 molvis 侧缺口 #4)。
- [x] 5. **Pin** 联调 — in-tree 测试经 `Molvis.from_inprocess`(无浏览器):exec 驱动真 stage API 往返 + 注入事件经 poll_events 送达(editable overlay 真跑通过)。
- [x] 6. **Index** — molvis 纳入 discovery source inventory(经 editable 信号;修复 `environment._top_level` 对 PEP 660 src-layout 的解析);`molmcp index` + `open_ref` 注入 drawing mixin docstring 页验证通过。
- [x] 7. **Document** — provider-design 条目 + guide 回路页(教回路不教 API)+ 同进程信任模型。
- [x] 8. **Note** in docs: e2e harness lives out-of-tree;不给产品树塞剧本。
- [x] 9. Hygiene: `/mol:simplify` ran clean(2 apply 修复;3 项 manual 移交 `/mol:refactor` 记录在案)。

## Testing

### In-tree(本 spec done 门槛)

- SessionStore CRUD + 撞名报错 + close 丢弃命名空间。
- journal cursor 单调 + truncated + 跨线程 append 安全 + payload 原样。
- exec:命名空间跨调用持久(第 1 次定义 `mol`,第 2 次可用);`stage` 预绑定;stdout/末表达式 repr/异常 traceback 三种返回形态;超大输出截断标记。
- **provider 代码零领域知识**:除 docstring 示例外,provider.py/session.py 无 molvis 方法名分支、无 molpy import、无 env 读取、无门控分支。
- **in-process transport(真 molvis,无浏览器)**:exec → stage API 往返 + 事件 journal 端到端(Task 5)。
- 缺 molvis 时 register 或 call 的失败形态稳定。

### Out-of-tree e2e(**不**作为本 spec `done` 门槛)

Sibling 目录(建议 `molcrafts/molvis-agent-e2e/`,**禁止**放进 `molmcp/` 或 `molvis/` 的 `examples/` / `tests/` 产品面):

1. 启动 `molmcp serve`(或等价)。
2. Agent:`open` → exec 建 aspirin 并 `stage.draw_frame(mol)` → 浏览器可见。
3. 人工或驱动选区 → `poll_events` 收到 `selection_changed`;exec `stage.get_selected()` 子 Frame 非空。
4. exec molpy 编辑 → `stage.clear()` → `stage.draw_frame(mol)` → canvas 更新。(「编辑选中」变体依赖 molvis 侧选区行号契约钉死;整分子替换变体无此依赖。)
5. `close`。

该 harness 可后补;实现本 provider 时 **不得** 为「图省事」把剧本塞进产品仓库。

## Out of scope

- 任何具名包装工具(复合或 1:1 皆禁)。
- Agent-facing 的 send_cmd/JSON-RPC 工具面(exec 内直接用 molvis Python API;裸 RPC 不进教学路径)。
- 环境变量开关、权限门控、沙箱/隔离(设计指令:本地 workbench 信任模型)。
- molvis 侧配套缺口的实现(选区行号契约、`NotConnectedError`、serve 环境构造回归)——molvis 另 spec;本 spec 仅在「molvis 侧配套缺口」表声明依赖。
- 官能团级 stitch / SMARTS 替换。
- 附着用户已独立启动的浏览器/WS session(跨进程 attach)。
- 把 e2e 剧本或 demo 脚本合入 molvis / molmcp 产品树。
- RDKit 直调。
- molmcp 内嵌 LLM 或自动跑对话 agent。
