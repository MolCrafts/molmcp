---
title: Environment auto-discovery — policy module (discover)
status: done
created: 2026-07-20
slug: env-auto-discovery-01-discover
supersedes: none
grilled: true
---

# Environment auto-discovery — policy module (discover)

## Summary

新增一个 app 层纯策略模块 `src/molmcp/environment.py`,它在**不导入、也不执行**目标 Python 环境代码的前提下,从一个环境中发现 MolCrafts 系包,并把每个包翻译成一条 discovery source spec 字符串。模块给出单一公共入口 `discover_sources(locator)`:`locator=None` 表示 molmcp 自身运行的当前环境(产出 `pkg:<name>` spec),显式 locator(venv 根 / python 可执行文件 / site-packages 目录)表示外部环境(产出 `local:<abspath>` spec)。识别机制分层且不含硬编码包名名单。本 sub-spec **只交付策略引擎与其单元测试,不接入 config/cli**(接线是 02-wire 的职责);它输出的 spec 字符串正是 `config` 与 `discovery/source` 已经共享的契约,因此下游 `SourceResolver` 无需任何改动即可消费。

## Design

### 模块定位与依赖边界

`src/molmcp/environment.py` 是 `config.py` / `runtime.py` 的 app 层同级模块,MCP-free。它**只**依赖标准库(`importlib.metadata`、`os`、`json`、`pathlib`、`sys`、`sysconfig`)与 `config.py` 中的 `ConfigurationError`(复用 fail-closed 异常类型,保持与 config 一致的报错惯例)。它**不导入** `molmcp.cli`、`molmcp.runtime`、`molmcp.server`、`molmcp.discovery`、`fastmcp`,也**不 import 被枚举的任何 dist**。本阶段 `config.py` 尚未反向导入本模块,故无循环导入。

### 数据结构(frozen dataclass,immutable)

- `DiscoveredSource`:一条发现结果。字段 `name`(已按 `config._SOURCE_NAME_RE` 语义 sanitized 的小写 source 名候选)、`spec`(`pkg:<top_level>` 或 `local:<abspath>`)、`identified_by`(命中的信号元组,取值来自固定字面量集合 `"entry_point" | "keyword" | "editable" | "override"`)、`distribution`(规范 dist 名)、`version`。
- `EnvironmentReport`:一次发现的完整诊断报告。字段 `locator`(原始 locator 字符串,`None`=self)、`is_self`(bool)、`site_paths`(实际枚举的 site-packages 绝对路径元组;self 时为空元组,表示走默认 meta-path finders)、`sources`(`DiscoveredSource` 元组,按 name 排序)、`skipped`(fail-soft 跳过的 dist 名 + 原因,便于诊断)、`excluded`(被 `MOLMCP_DISCOVER` 的 `-name` 排除的 dist 名)。提供 `to_dict()` 产出 JSON-able 结构,供 02-wire 在 `molmcp info` 中展示。

### 公共 API

- `resolve_site_paths(locator: str) -> tuple[Path, ...]` —— 外部环境 locator 归一化(纯路径 glob,**绝不 subprocess 运行目标 python**):
  - locator 指向 site-packages 目录(含 `*.dist-info` 或目录名为 `site-packages`)→ 原样使用。
  - locator 指向 venv 根(含 `pyvenv.cfg`,或含 `bin/`/`Scripts/`)→ glob `<venv>/lib/python*/site-packages`(posix)与 `<venv>/Lib/site-packages`(windows),收集存在者。
  - locator 指向 python 可执行文件 → 结构化推导 env 根为 `<exe>.parent.parent`,再套用 venv-根 逻辑;**不运行该 exe**。
  - 路径不存在,或无法解析出任何存在的 site-packages 目录 → 抛 `ConfigurationError`(fail-closed)。
- `discover_sources(locator: str | None = None) -> EnvironmentReport` —— 顶层入口:
  - `locator is None`(self):以 `importlib.metadata.distributions()`(默认 finders)枚举当前解释器环境,家族包产出 `pkg:<top_level>`。
  - `locator` 给定(foreign):`resolve_site_paths(locator)` → `importlib.metadata.distributions(path=[...])` 枚举,家族包产出 `local:<abspath>`。
  - 内部读取 `os.environ["MOLMCP_DISCOVER"]`(信号 d 覆盖;测试用 `monkeypatch.setenv` 注入)。

### 家族识别(分层信号,读元数据不 import)

对每个 dist,按以下信号判定是否家族包,并记录命中信号到 `identified_by`:

- **(a) entry-point 组**:`any(ep.group.startswith("molmcp.") for ep in dist.entry_points)`(`molmcp.providers` / `molmcp.capabilities` / `molmcp.overlays` 等)。从 dist-info 元数据读取,不 import 包代码。
- **(b) `molcrafts` keyword**:解析 `dist.metadata` 的 `Keywords` 字段(逗号/空格切分,大小写不敏感)包含 `molcrafts`。
- **(c) editable / PEP 610**:`dist.read_text("direct_url.json")` → JSON **fail-soft** 解析,`dir_info.editable is True`。这是**当前 `/Users/roykid/work/molcrafts/.venv` 唯一能命中 molexp 的信号**(molexp 自身元数据既无 `molmcp.*` entry point 也无 `molcrafts` keyword),故 (c) 默认开启且不可省。
- **(d) `MOLMCP_DISCOVER` 覆盖**:`+name` 强制纳入(即使无 a/b/c 信号,`identified_by` 记 `"override"`);`-name` 强制排除(即使有信号,记入 `excluded`)。name 匹配用 PEP 503 归一化(小写、`-_.` 连续段折叠为 `-`)。
- 判定:`(a or b or c) and not force-excluded`,或 `force-included(+)`。三信号可同时命中,`identified_by` 记全部。

### spec 产出与包目录定位(不 import)

- **self 家族包** → `pkg:<top_level>`。top-level 取 `dist.read_text("top_level.txt")` 首行,缺失则回退 `dist.name` 的 `-`→`_` 归一化。`pkg:` 由 `resolve_pkg` 在当前进程内 late-bind(editable finder 自动跟踪本地 checkout)。
- **foreign 家族包** → `local:<abspath>` 指向**包目录**(非 git repo root):
  - 非 editable wheel:包目录 = `<site-packages>/<top_level>`(须存在)。
  - editable:解析 `direct_url.json` 的 `url`(`file://` → checkout 路径),包目录取 `<checkout>/<top_level>` 或 `<checkout>/src/<top_level>` 中含 `__init__.py` 者;二者皆缺则 fail-soft 跳过并记入 `skipped`,不产出坏 spec。
  - 取包目录而非 repo root 是刻意取舍:确定性、匹配可导入 Python 面,且 `resolve_local_path` 已对含 `__init__.py` 的目录做 parent-as-root。**代价**:同级 Rust(molrs)/ TS(molvis)源码不经此路径索引——列入 Out of scope。
- **source 名**:dist 名 sanitized 为小写、仅保留 `[a-z0-9._-]`、首字符字母。本阶段只产出候选名;与 `workspace` 的去重/最终校验属 02-wire 的 config 职责。

### Fail-soft 与 fail-closed 边界

单个 dist 在读元数据/解析 `direct_url.json` 时抛错 → 跳过该 dist 并记入 `skipped`,**绝不中断整体枚举**(复用 `load_installed_manifests` / `discover_providers` 的 enumerate→per-item→fail-soft 形状)。**仅 locator 本身无效/不存在**才 fail-closed 抛 `ConfigurationError`。

### Reuse decision

- `load_installed_manifests`(`registry/entrypoints.py:25`)—— **new**:仅复用其 enumerate→per-item validate→fail-soft collect 的**形状**,不调用它;`discover_sources` 枚举的是 `distributions(path=...)` 这一不同语料。
- `discover_providers`(`provider.py:41`)—— **new**:信号 (a) 以只读方式消费 `dist.entry_points` 的 `molmcp.*` 组,不调用 `discover_providers`,不扩展 `molmcp.providers` entry-point schema(CLAUDE.md:never change casually)。
- `ConfigurationError`(`config.py:26`)—— **reuse**:直接复用作 fail-closed 异常类型,保持 config 报错惯例一致。
- 以下 librarian 候选**本 sub-spec 不触碰,顺延至 02-wire,届时被本模块产出的 spec 字符串原样消费、不修改**:`AppConfig.default` / `load_config` / `_resolve_source_spec`(config.py)、`resolve_local_path` / `resolve_pkg` / `_package_dir`(discovery/source/local.py)、`SourceResolver.resolve`(discovery/source/resolver.py)、`build_registry` / `_load_installed`(runtime.py)。

## Files to create or modify

- `src/molmcp/environment.py` (new) —— 策略模块:`DiscoveredSource`、`EnvironmentReport`、`resolve_site_paths`、`discover_sources`。
- `tests/test_environment.py` (new) —— locator 归一化、家族信号、spec 产出、fail-soft/fail-closed 的单元测试。
- `regressions/env-auto-discovery-01-discover.py` (new) —— 合成 site-packages fixture 上的端到端 regression(仅经公共 API)。

## Tasks

- [x] Write failing tests for site-packages locator normalization (tests/test_environment.py)
- [x] Implement resolve_site_paths locator normalization in src/molmcp/environment.py
- [x] Write failing tests for family identification signals and spec emission (tests/test_environment.py)
- [x] Implement discover_sources with distributions(path=...) enumeration, signals a/b/c/d, and spec emission in src/molmcp/environment.py
- [x] Add docstrings per google style to environment.py public API
- [x] Add regression example regressions/env-auto-discovery-01-discover.py (synthetic site-packages, public API only)
- [x] Run full check + test suite
- [x] Hygiene: /mol:simplify ran clean (0 auto-fixes; 1 manual handoff: fixture-builder dedup → /mol:refactor)

## Testing strategy

- **Happy path**
  - `resolve_site_paths` 对 site-packages 目录、posix venv 根(`lib/python3.X/site-packages`)、python 可执行文件三种 locator 各返回存在的 site-packages 路径。
  - `discover_sources(None)`(self,monkeypatch `distributions` 返回带 `molmcp.*` entry point 的 fake dist)产出 `pkg:<top_level>` 且 `identified_by == ("entry_point",)`。
  - `discover_sources(<synthetic site-packages>)`(foreign)对含 `direct_url.json`(editable)的 dist 产出 `local:<pkg-dir-abspath>` 且 `identified_by` 含 `"editable"`。
- **Edge cases**
  - locator 不存在 / 无法解析出 site-packages → `ConfigurationError`(fail-closed)。
  - 信号 (b) `molcrafts` keyword 单独命中;三信号同时命中时 `identified_by` 记全部。
  - editable src-layout(`<checkout>/src/<pkg>`)与 flat-layout(`<checkout>/<pkg>`)均正确定位包目录,且**不**指向 repo root。
  - editable `direct_url.json` 损坏 / 包目录缺失 → fail-soft 跳过并记入 `skipped`,其余 dist 仍被枚举。
  - 无任何信号的第三方 wheel(numpy-like fixture)→ 不产出。
  - `MOLMCP_DISCOVER="+extra,-molpy"`:`+extra` 强制纳入(`identified_by` 含 `"override"`),`-molpy` 强制排除(记入 `excluded`);名字按 PEP 503 归一化匹配。
  - `identified_by` 字面量(`"entry_point"/"keyword"/"editable"/"override"`)作为诊断契约被钉住断言。
  - `environment.py` 静态断言:无 `subprocess`/`os.system`/`runpy`/对目标 dist 的 `import_module`;无 `molmcp.cli`/`runtime`/`server`/`discovery`/`fastmcp` 导入;无硬编码 MolCrafts 包名名单。
- **Regression example**:`regressions/env-auto-discovery-01-discover.py` —— 构造一个含四个 fake `.dist-info` 的合成 site-packages(分别命中信号 a、b、c,外加一个无信号的非家族 wheel),调用 `discover_sources(<那个目录>)`,断言产出的 `DiscoveredSource.spec` 与 `identified_by` 集合与期望参考值逐一相符,并打印报告后以 0 退出。此为最小、仅经公共 API 的库外用户用例。
- 确定性均通过 `tests/registry/test_entrypoints.py:41-91` 的 `monkeypatch.setattr(importlib.metadata, ...)` 模板 + 磁盘上的真实(内容伪造)`.dist-info` 目录实现,不依赖真实已安装包。

## Out of scope

- 接入 `config.py` 无文件分支、`cli.py` 的 `--env`/`MOLMCP_ENV`、`runtime.py` 的 `info`/`config_summary` 诊断展示 —— 属 02-wire。
- 对 editable checkout 上溯 git repo root 以索引同级 Rust(molrs)/ TS(molvis)源码 —— 本阶段只取包目录;polyglot 源索引为相邻开放问题。
- 外部环境的 registry manifest(process-bound `entry_points` 同限制)—— 相邻开放问题,不在本链范围。
- 上游 sibling 包新增 `molcrafts` keyword / `molmcp.*` entry point 以便作为非 editable wheel 被发现 —— adoption note,不是本 repo 的任务。
