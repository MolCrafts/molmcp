# Notes

Evolving architectural decisions. Appended by `/mol:note`; newest first.

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
