---
title: Retrieval-first discovery; call graph as an optional evidence feature
status: code-complete
created: 2026-07-07
---

# Retrieval-first discovery; call graph as an optional evidence feature

## Summary

把 discovery 的主干从"代码图遍历"改回它真正的任务——**能力检索**:
agent 问"用什么 API 做 X",我们返回排序正确的符号目录。当前
`find_capability` 的排序把**猜测出来的调用边**当成重要性信号
(`caller_count`),导致一个字母序 sink 节点(`AcReader.read`)被灌成
假热点,把语义正确的结果挤到后面(实测 "read lammps" 把
`read_lammps_data` 压到第 4)。

本重构做三件事:(1) 让排序只吃**检索质量 + 可靠结构信号**,把调用图
彻底移出排序路径;(2) 修正 resolver 的两个具体缺陷(丢失构造边、盲选
sink),让保留下来的调用图**诚实**;(3) 把 code graph
(`relations`/callers/callees)保留为一个**显式的可选证据功能**——按
provenance 标注、默认偏好已解析边,但永不再参与排序。同时建立一个
**确定性 golden-set 回归**(+ 可选的轻量模型相关性评审)来长期卡住
这类退化。

## Domain basis

代码智能领域把这件事分三层(见调研):
- **名称解析 / 调用解析**是 IDE **导航**(跳转、找引用、影响分析)的核
  心,成熟做法需要类型推断(CHA/RTA/points-to,或复用 pyright/Jedi;
  Python 专用库如 PyCG)。molmcp 现在**没有任何类型推断**,`_resolve_call`
  对 `x = C(...); x.m()` 无法确定接收者类型。
- 我们的实际任务不是导航而是**检索**(catalog + search),其核心是
  **索引 + 排序**,不是边。把导航范式的核心(边)搬来当排序信号是范式
  错配——这正是 bug 的来源。
- 因此:检索当主干;调用图作为可选功能保留,但必须(a) 退出排序,
  (b) 用 provenance 如实标注置信度。真正的类型推断(Jedi/PyCG/SCIP)是
  **后续独立轨道**,不在本 spec。

## Design

**根因(已在代码中定位)**
- `resolve.py:_resolve_call` 认不出接收者类型时,落到全局同名池,
  `_pick` 用 `sorted(pool, key=node.id)[0]` 盲选——`node_id =
  f"{file}#{qualname}#{kind}"` 使其等价于**按文件路径字母序**,`ac.py`
  永远赢 → 全项目无法解析的 `.read()` 都被灌进 `AcReader.read` 这个 sink。
- 同函数只接受 `_CALLABLE_KINDS = {FUNCTION, METHOD, TEST}`,类实例化
  `LammpsDataReader(...)` 目标是 CLASS 被过滤 → **构造边整条丢失**。
- `store.incoming_edge_counts` 只按 `EdgeKind.CALLS` 计数、**不按
  provenance 过滤**;`evidence.py:170` 把它喂给 `RankCandidate.caller_count`;
  `ranking._score` 里 `W_CALLERS * log1p(caller_count)` 把 sink 的假计数
  变成排序分数。

**主干:排序只用干净信号(`ranking.py` + `evidence.py` + `graphstore.py`)**
- 新增按 provenance 过滤的入边计数:`graphstore.incoming_edge_counts`
  增加 `provenance` 过滤参数(或新增 `_resolved` 变体),`query` 暴露
  "仅已解析(RESOLVED)调用者数"。
- `ranking._score`:移除对未过滤 `caller_count` 的依赖。调用者信号改为
  **仅已解析边**,且权重下调(结构证据,非主排序依据);主排序依据是
  **字段加权的词法匹配**(命中 name/qualname ≫ summary ≫ body)+ 现有
  的 `is_exported` / examples / tests / `kind_prior`。`rank_signals`
  输出同步更新,使每项可解释。

**让保留的调用图诚实(`resolve.py`)**
- 修 Bug B:`_resolve_call` 对类实例化放行——目标为 CLASS 时,连一条
  到该类(经 import-scoped 命中记 RESOLVED)的 CALLS 边,恢复构造边。
- 修盲选 sink:当同名兜底池 `>1` 候选且无 import-scoped 置信时,**不再
  发一条冒充真调用的单条 HEURISTIC 边**;改为不发边(或记为显式
  ambiguous,且**一律排除出 caller_count**)。provenance 保持如实。

**Code graph 作为可选功能(保留,不删)**
- `relations`(callers/callees/impact)与 `describe_symbol` 继续可用;
  响应中 `provenance` 字段(evidence.py 已有)成为一等公民,默认优先
  展示 RESOLVED,HEURISTIC 明确标注为"猜测"。
- 在 CLAUDE.md / `.claude/notes/` 记录新定位:**调用图是可选证据功能,
  已从排序路径移除**;语义/类型推断增强是后续轨道。

**两种检索模式(Point 3;基本已被现有工具覆盖,只需保证质量)**
- 全量浏览:`outline` / `find_capability` 返回的每行含
  `名字·类型·签名·一句话摘要·模块`,足以让 agent"看有啥能力"。
- 关键词收窄:`find_capability` / `search_symbols` 在干净排序下按关键词
  返回 top-k。语义向量检索(小型本地 embedding)列为 Out of scope 的
  下一档。

**测试用轻量模型**
- 主回归是**确定性**的(top-k 断言,无需模型)。
- 额外提供一个**可选**的相关性评审脚本,用轻量模型
  (`claude-haiku-4-5`)对 golden set 打相关性分;仅在
  `ANTHROPIC_API_KEY` 存在时运行,缺失即 SKIP,**不进 CI 默认门禁**。

## Files to create or modify

- `src/molmcp/discovery/ranking.py` — 重写 `_score` / `rank_signals`:移除
  未过滤 caller 信号,改字段加权词法 + 仅已解析 caller(低权)。
- `src/molmcp/discovery/store/graphstore.py` — `incoming_edge_counts` 增
  provenance 过滤(或新增已解析变体)。
- `src/molmcp/discovery/query.py` — 暴露仅已解析调用者计数。
- `src/molmcp/discovery/evidence.py` — 给 `RankCandidate` 喂已解析
  caller 计数;确保 relations 响应携带 provenance。
- `src/molmcp/discovery/resolve.py` — 修 Bug B(类实例化放行)+ 修盲选
  sink(多候选无置信时不发冒充边、排除出计数)。
- `tests/discovery/golden_queries.yaml` (new) — query → 期望 top-k qualname。
- `tests/discovery/test_golden_ranking.py` (new) — 确定性 top-k 断言 +
  provenance 完整性断言。
- `scripts/eval_relevance.py` (new) — 可选 Haiku 相关性评审,API key 门控。
- `CLAUDE.md` — 记录"调用图=可选证据功能,已移出排序"的定位。

## Tasks

- [x] Add provenance-filtered incoming CALLS counting in `graphstore` + expose "resolved-only caller count" via `query`.
- [x] Rework `ranking._score` / `rank_signals`: drop unfiltered `caller_count` (resolved-only upstream); field-weighted lexical via bm25 column weights in `graphstore.search`; callers at reduced weight; keep exported/examples/tests/kind priors; exclude navigational nodes from matches.
- [x] Fix `resolve._resolve_call` Bug B: resolve class-instantiation calls to the CLASS node (restore constructor edges).
- [x] Fix `resolve._resolve_call` / `_pick` sink: when the same-name fallback pool has >1 candidate and no import-scoped confidence, emit no impersonating edge and exclude it from caller_count.
- [x] Build deterministic golden-set regression (`golden_queries.py` + `test_golden_ranking.py`) incl. "read lammps → LammpsDataReader/read_lammps_data at rank 1; AcReader.read not top-3". (RED)
- [x] Add provenance-integrity tests: resolved constructor edge exists on `read_lammps_data`; `AcReader.read` resolved caller_count excludes cross-file unresolved `.read()` calls. (RED — `test_receiver_resolution.py` + `test_provenance_counts.py`)
- [x] Preserve call graph as a labeled feature: relations / find_capability responses expose `provenance` and prefer RESOLVED; document the "call graph = optional evidence, out of ranking" stance in `CLAUDE.md`.
- [x] Add opt-in `scripts/eval_relevance.py` lightweight-model (`claude-haiku-4-5`) relevance judge over the golden set, gated on `ANTHROPIC_API_KEY`, excluded from default CI.

## Testing strategy

- Deterministic golden-set: `pytest tests/discovery/test_golden_ranking.py`
  asserts top-k qualnames per query; the "read lammps" case is the canary.
- Provenance integrity: unit tests over the resolver on a small fixture that
  reproduces the `reader.read()` / `LammpsDataReader(...)` shape.
- Ranking unit tests: `rank_signals` no longer contains an unfiltered
  caller contribution; a node with only heuristic incoming edges scores 0
  on the caller feature.
- Optional lightweight-model judge: `scripts/eval_relevance.py` on Haiku,
  run only when `ANTHROPIC_API_KEY` is set; prints SKIP otherwise.
- Regression guard: whole `tests/discovery/` suite stays green.

## Out of scope

- 语义向量检索(小型本地 embedding + hybrid rerank)——下一档 spec。
- 真正的接收者类型推断(Jedi / PyCG / pyright-based SCIP)——独立轨道;
  本 spec 只保证"认不出类型时不污染",不解决"认出类型"。
- 采纳 stack-graphs / SCIP 换底座。
- 跨语言(ts/rust/cpp)analyzer 的等价修复——先在 Python analyzer 验证。
