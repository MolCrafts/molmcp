---
title: Environment auto-discovery — wire into app assembly (wire)
status: approved
created: 2026-07-20
slug: env-auto-discovery-02-wire
depends_on: env-auto-discovery-01-discover
supersedes: none
grilled: true
---

# Environment auto-discovery — wire into app assembly (wire)

## Summary

把 01-discover 交付的 `molmcp.environment.discover_sources` 接入 app 装配层,使 molmcp 在**没有 molcrafts.json** 时,默认行为从"只索引 cwd workspace"升级为"workspace + 从 Python 环境自动发现的每个 MolCrafts 系包各一个 discovery source"。改动集中在三个 app 层文件:`config.py`(无文件分支折叠发现结果)、`cli.py`(`--env` flag + `MOLMCP_ENV` 环境变量选择目标环境)、`runtime.py`(把 `EnvironmentReport` 诊断透出到 `molmcp info` / `config_summary`)。**molcrafts.json 存在时逐字生效、绝不增强**;`workspace` source 无条件保留。发现结果以已就绪的 spec 字符串(`pkg:<name>` / `local:<abspath>`)存入 `AppConfig.sources`,被现有 `SourceResolver` 原样消费,`discovery/source` 叶子零改动。

## Design

### 依赖方向与循环导入规避

`environment.py`(01)在模块顶层 `from .config import ConfigurationError`。因此 `config.py` **不得**在模块顶层 import `environment`,否则形成 `config ↔ environment` 循环。解决:`load_config` 的无文件分支内做**函数级** `from .environment import discover_sources`——这与 `discovery/source/resolver.py` 现有的函数级 `from .local import ...` / `from .github import ...` 惰性导入完全同构(该文件已确立源码中惰性子模块导入以打破耦合的先例)。`cli.py`/`runtime.py` 对 `environment` 无直接依赖(它们只经 `AppConfig` 间接消费诊断字典)。

### (1) config.py —— 无文件分支折叠(generalize)

- `AppConfig` 新增可选字段 `discovery: dict[str, Any] | None = None`(承载 `EnvironmentReport.to_dict()` 的 JSON-able 诊断;存**字典**而非 `EnvironmentReport` 对象,避免 config 顶层依赖 environment 类型 → 无循环)。`from_dict`(显式配置)保持 `discovery=None`。
- `AppConfig.default` generalize 签名:`default(cls, workspace_root, *, discovered: Iterable[tuple[str, str]] = (), discovery: dict[str, Any] | None = None)`:
  - `workspace` source 无条件先置:`sources = {"workspace": str(root)}`。
  - 依序追加 `discovered`(01 已按 name 排序):每条经 `_resolve_source_spec(spec, root)` 归一(见下)后写入。
  - **名称冲突处理**(确定性):若某发现名等于 `workspace` 或与已加入的发现名相同,追加最小可用后缀 `-2`/`-3`/…,并保证结果满足 `config._SOURCE_NAME_RE`;`workspace` 永远映射到 cwd。
  - 传入的 `discovery` 存入新字段。
- `_resolve_source_spec` generalize:passthrough 集合从 `("pkg:", "github:")` 扩为 `("pkg:", "github:", "local:")`——发现的 `local:<abspath>` 已是绝对路径,原样返回;`pkg:`/`github:`/相对路径 三种既有行为不变(现有 test_config.py:17 的 `pkg:molpy` 与 `./repo` 均不受影响)。`local:` 在此前从非 config 级合法形式,新增 passthrough 是严格改进,非回归。
- `load_config` generalize:新增关键字参数 `env_locator: str | None = None`;仅**无文件分支**(`path is None and not config_path.is_file()`)启用自动发现:
  ```
  from .environment import discover_sources          # 函数级,破循环
  locator = env_locator if env_locator is not None else os.environ.get("MOLMCP_ENV")
  report = discover_sources(locator)                 # 坏 locator → ConfigurationError 直接上抛(fail-closed)
  return AppConfig.default(
      Path.cwd(),
      discovered=[(s.name, s.spec) for s in report.sources],
      discovery=report.to_dict(),
  )
  ```
  `MOLMCP_ENV` 在 config.py 边界读取(fail-closed 惯例集中处),使直接调用 `load_config()` 的库内嵌用户与无参 MCP 启动都受益。**molcrafts.json 存在的分支保持字节级不变**(不注入发现结果,`discovery` 恒 None)。

### (2) cli.py —— locator 选择面(`--env` + `MOLMCP_ENV`)

- 在 `_config_argument(parser)` 上追加 `--env`(`metavar="LOCATOR"`,`default=None`,help:venv 根 / python 可执行文件 / site-packages 目录;缺省=当前环境),使 serve/info/search/explore/index 与 `registry list` 同时获得该 flag。
- 线接:把 `args.env` 作为 `env_locator` 传入 `load_config`。将 `_load(path)` 调整为携带 locator(如 `_load(args)` 读 `args.config` 与 `args.env`,或新增 `_env_locator(args)` 助手),更新 `_serve`/`_collection`/`_registry` 调用点。**优先级 flag > `MOLMCP_ENV` > None(self)**:cli 传 flag 值(可能 None),`load_config` 在 None 时回落 `MOLMCP_ENV`。
- 无参 MCP 启动(`molmcp` → `["serve"]` → `_serve` → `_load`)因此天然覆盖 env-var 路径(`.mcp.json` 只能塞 env)。
- 坏 locator 抛的 `ConfigurationError` 经 `main` 既有 `except (ConfigurationError, ...)` 分支打到 stderr 并 **返回 exit 2**(复用现有错误路径,与 `test_unknown_index_source_is_user_error` 同形)。

### (3) runtime.py —— 诊断透出

- `build_collection(config, registry)` 的 `metadata` 追加 `"discovery": config.discovery`。因 `CollectionIndex.info()` 已把 `self.metadata` 整体放在返回值的 `"configuration"` 键下,`molmcp info` 自动在 `configuration.discovery` 处呈现:环境路径(`environment`/`site_paths`)、发现的每个包(`sources[*]` 含 `spec` 与 `identified_by` 信号)、`skipped`、`excluded`。**无需改 collection/index.py**。
- `config_summary(config)` 追加 `"discovery": config.discovery`(保持 secret-free——只含路径、包名、信号字面量,无凭据)。
- 这样 `molmcp info` 能回答"自动发现找到了哪些包、来自哪个环境、凭什么信号(identified-by)、跳过/排除了什么"——可诊断性即验收的一部分。

### Reuse decision(结清 01 顺延的判定)

- `AppConfig.default`(config.py:222)—— **generalize**:`workspace` 无条件保留 + 追加发现 specs + 携带诊断;含冲突处理。
- `load_config`(config.py:349)—— **generalize**:仅无文件分支启用发现,新增 `env_locator` + `MOLMCP_ENV` 回落 + 函数级 environment 导入;molcrafts.json 分支字节不变。
- `_resolve_source_spec`(config.py:328)—— **generalize**:passthrough 增列 `local:`;无新形式,既有行为保留。
- `resolve_local_path`(discovery/source/local.py:76)—— **reuse 不改**:消费发现的 `local:<abspath>`(parent-as-root 已具备)。
- `resolve_pkg`(local.py:93)+ `_package_dir`(local.py:16)—— **reuse 不改**:消费 self-env 的 `pkg:<name>`;仅**补直接单测**(源码零改)。
- `SourceResolver.resolve`(discovery/source/resolver.py:64)—— **reuse 不改**:前缀分派已含 `pkg:`/`local:`,不加新分支。
- `build_registry`/`_load_installed`(runtime.py:57)—— **reuse 不改**:registry 装配不动;仅 `build_collection` metadata 与 `config_summary` 增诊断字典。外部环境 registry manifest 仍 out of scope。
- `discover_providers`(provider.py)/ `load_installed_manifests`(entrypoints.py)—— 本 sub-spec **不触碰**(01 已 pattern-only 消费)。

## Files to create or modify

- `src/molmcp/config.py` —— generalize `AppConfig.default`/`load_config`/`_resolve_source_spec`;`AppConfig` 增 `discovery` 字段。
- `src/molmcp/cli.py` —— `_config_argument` 增 `--env`;线接 `env_locator` → `load_config`。
- `src/molmcp/runtime.py` —— `build_collection` metadata + `config_summary` 透出 `config.discovery`。
- `tests/test_config.py` —— 扩 `:10`(默认=workspace+发现,monkeypatch `discover_sources`)、`:17`(显式配置不被增强、`discovery is None`);增冲突、fail-closed 坏 locator、`MOLMCP_ENV` 回落。
- `tests/test_cli_vnext.py` —— `--env` 线接 + 优先级 + 坏 locator exit 2。
- `tests/test_runtime.py` —— `build_collection`/`config_summary`/`info()` 诊断透出。
- `tests/discovery/test_local_source.py` —— 补 `resolve_pkg` 直接单测(仅新增测试,不改 discovery 源码)。
- `regressions/env-auto-discovery-02-wire.py` (new) —— 端到端 regression(仅经公共 API)。

## Tasks

- [ ] Write failing tests for no-file auto-discovery folding and explicit-config-not-augmented (tests/test_config.py)
- [ ] Generalize AppConfig.default, load_config, and _resolve_source_spec plus the discovery field in src/molmcp/config.py
- [ ] Write failing tests for --env flag, MOLMCP_ENV precedence, and bad-locator exit 2 (tests/test_cli_vnext.py)
- [ ] Wire --env onto _config_argument and thread env_locator into load_config in src/molmcp/cli.py
- [ ] Write failing tests for auto-discovery diagnostics in build_collection, config_summary, and info (tests/test_runtime.py)
- [ ] Surface EnvironmentReport diagnostics via build_collection metadata and config_summary in src/molmcp/runtime.py
- [ ] Add a direct resolve_pkg unit test for the pkg: spec path (tests/discovery/test_local_source.py)
- [ ] Add regression example regressions/env-auto-discovery-02-wire.py (synthetic env locator, public API only)
- [ ] Run full check + test suite

## Testing strategy

- **Happy path**
  - monkeypatch `config.discover_sources` 返回两条 fake `DiscoveredSource`(一条 `pkg:`、一条 `local:<tmp-pkg>`),`load_config()`(cwd 无 molcrafts.json)→ `sources == {"workspace": <cwd>, <n1>: <spec1>, <n2>: <spec2>}` 且 `config.discovery` 含二者 `identified_by`。
  - `build_collection(config).metadata["discovery"]` 与 `collection.info()["configuration"]["discovery"]` 含环境路径 + 每包 `identified_by`;`config_summary(config)` JSON 同样含之且不含凭据。
- **Edge cases**
  - 显式 molcrafts.json:`load_config(path)` 返回文件内 sources **原样**、无发现项、`config.discovery is None`,且 `discover_sources` 未被调用(monkeypatch 计数为 0)。
  - 名称冲突:发现名 `workspace` 或彼此重名 → 确定性后缀去歧义,所有名满足 `_SOURCE_NAME_RE`,`workspace` 仍指向 cwd。
  - fail-closed:`discover_sources` 抛 `ConfigurationError`(坏 locator)→ 由 `load_config` 直接上抛,不静默回落 workspace-only。
  - `_resolve_source_spec`:`pkg:`/`github:`/`local:` 三前缀原样返回;相对路径仍解析为 abspath。
  - CLI 优先级:`--env X` → `discover_sources` 收到 `X`;无 flag 但 `MOLMCP_ENV=Y` → 收到 `Y`;皆无 → 收到 `None`(经 monkeypatch 捕获实参断言)。
  - CLI 坏 locator:`--env <不存在>` → stderr 有 `molmcp:` 前缀信息且 `cli.main(...) == 2`。
  - `resolve_pkg` 直接单测:`pkg:fixture_pkg` → snapshot 以包父目录为 root,qualname 含包名(复用 `tests/fixture_pkg`)。
- **Regression example**:`regressions/env-auto-discovery-02-wire.py` —— 构造合成环境(临时 site-packages + 一个真实存在的最小家族包目录),经 `load_config(None, env_locator=<该目录>)` → `build_collection` → `collection.info()`,断言发现的包作为一条 source 出现、其 `environment` 路径与 `identified_by` 信号可见,并以 0 退出。仅经公共 API,如库外用户所为。
- 确定性均以 monkeypatch(`discover_sources` / `MOLMCP_ENV` / `build_collection`)达成,不依赖真实已安装的 molcrafts 包。

## Out of scope

- 对 editable checkout 上溯 git repo root 以索引同级 Rust(molrs)/ TS(molvis)源码 —— 仍取包目录(01 决定)。
- 外部环境的 registry manifest(process-bound `entry_points` 同限制)—— 相邻开放问题,不接入。
- 上游 sibling 包新增 `molcrafts` keyword / `molmcp.*` entry point 的 adoption note —— 非本 repo 任务。
- 修改 `discovery/source`、`collection/index.py`、`molmcp.providers` entry-point schema —— 均不触碰。
