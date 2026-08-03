# Notes

Evolving architectural decisions. Appended by `/mol:note`; newest first.

## 2026-08-02 — molvis provider = 工作台原语,不是接口翻译层

molmcp 对 molvis 的角色定位:**把「活着的 Python 会话」借给 agent,而不是替
molvis 说话**。词汇表永远是 molpy/molvis 自己的公开 API;molmcp 只提供
5 个通用原语:`open` / `close` / `list_sessions` / `exec`(持久命名空间,
`stage` 预绑定)/ `poll_events`(事件 journal)。

依次否决过的三种形态(不要再提):

1. **复合便捷工具**(`show_smiles` = parse+embed+store+draw)——一个名字
   多个动作,隐藏状态迁移。
2. **1:1 具名包装目录**(`parse_molecule`/`clear`/`draw`/…)——粒度对了,
   但仍是 molmcp 必须与上游同步维护的镜像词汇。
3. **agent-facing JSON-RPC `call(method, params)`**——把 molvis Python↔前端
   的**内部** wire 协议提升成公共 API;且 frame 编码仍需进程内 Python,
   回路闭合不了。

拍板约束:**严禁环境变量开关;不设权限/opt-in 门控**(本地 workbench 信任
模型,与 Jupyter kernel 同级,docs 一句话说明,不做机制)。molq 的
`MOLMCP_MOLQ_SUBMIT` 属 legacy,不再扩散该模式。

架构定型为**四方**(一个会话,两个表面,两个意志):**人操作**(浏览器
UI,意志之一)、**canvas 显示**(molvis viewer,投影表面)、**agent 控制**
(MCP 5 原语,意志之二)、**代码操作**(molmcp serve 进程内 Python 会话,
持有 mol + stage,一切领域调用只在此)。四条边:人↔canvas(molvis 前端)、
canvas↔代码(molvis 内部 WS 协议,molmcp 不碰不暴露)、agent↔代码
(molmcp 工作台契约:exec + namespace + journal)、人↔agent(host 对话)。
真相单源:mol 在代码层,canvas 只是投影;两个意志经会话状态异步汇合。
附着外部已启动会话不在设计内(out of scope,非分期承诺)。

**选区↔行号契约:成立**(2026-08-03 对 molvis 前端源码核实,推翻了
spec 期的「未定,阻塞局部编辑」判断)。三处独立证据:`entity_source.ts:196`
建原子时 `atomId: index`;`selection_manager.getSelectedBondIds` 注释
「和 atom ids 一样,都是当前 frame block 的行号」;`commands/selection.ts`
的 `getSelectedCommand` 直接以选中 id 作行号切片(「sliced by row index」)。
故 **clear + 单次 `draw_frame(mol)` 后,选区 `atom_ids` 即
`list(mol.atoms)` 下标**,基于选区的局部图编辑今天就能做。前提是那条
clear 纪律:不 clear 连画两次,live frame 累加,行号指向合并帧。

molvis 侧配套缺口(molvis 另 spec,molmcp 不代偿):① 上述行号契约**缺
回归保护** —— `stage/tests/` 无 `getSelectedCommand` 行号语义测试,欠
一条 pin test(不是欠 API);② `NotConnectedError` 替代未连接时的 10s
阻塞超时;③ serve 环境构造回归;④ EventBus 无通配订阅,journal 只能
列举已知事件名(`session.py SUBSCRIBED_EVENTS` 是唯一在册的上游词汇)。
人工验收剧本:`../molvis-agent-e2e/PLAYBOOK.md`(out-of-tree)。

## 2026-07-22 — Molq provider in molmcp

First-party molq MCP tools live in **molmcp**:

```
src/molmcp/providers/molq/
  __init__.py
  provider.py          # MolqProvider
```

```toml
[project.entry-points."molmcp.providers"]
molq = "molmcp.providers.molq:MolqProvider"
```

- molq (`molcrafts-molq`) is a pure job-queue library — no FastMCP.
- Provider lazy-imports molq; missing install → clear register/call error.
- Tools:
  - Read-only: `list_jobs`, `get_job`, `job_logs`, `list_destinations`,
    `list_queue`
  - Opt-in mutate (`MOLMCP_MOLQ_SUBMIT=1` / `allow_submit=True`):
    `submit_job` (argv, no block-wait), `cancel_job`
- Cleanup/watch/daemon, full Submitor mirror, Nerve reverse-control, batch
  loops: out of MCP (CLI/script/molexp).

Same placement rule as `providers/molexp/`. Contract:
`docs/concepts/provider-design.md`.

## 2026-06-10 — discovery 三 spec 链落地时捕获的规则

- **SCHEMA_VERSION 链规则**：每个改变持久化图内容（节点/边集合或其语义）的
  spec 各自将 `SCHEMA_VERSION` +1（ranking→2，conventions→3）。只读消费图的
  改动（如 lint）不 bump。`ANALYZER_VERSION` 仅在分析器输出变化时 bump。
- **overlay 哨兵单点定义**：合成文件哨兵 `"<catalog>"` 是 `node_id()` 的输入，
  在 `overlay/__init__.py` 定义一次（`CATALOG_FILE`），catalog.py 与
  conventions.py 复用——再次声明会让 overlay 节点 ID 命名空间静默分裂。
- **测试只用模块级 import**：函数内 import 仅限可选依赖。
- **窄域 `# type: ignore[<code>]` 在故意违型的测试（如 frozen dataclass
  突变测试）中允许；裸 `# type: ignore` 不允许。**
- **MCP payload 契约测试钉序列化字面量**（如 `"resolved"`），不引用枚举成员——
  测的是 wire format。
