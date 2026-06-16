# STATUS — 当前开发状态

> **这份文件回答**："现在做到哪？下一步？被什么挡住了？"
>
> **特性**：**瞬时状态**。**软上限约 80 行**。可以覆盖。
> 有价值的内容**先**沉淀到 `MAP.md`（结构变化）或 `DECISIONS.md`（理由），再覆盖这里。
>
> **谁该读**：每个新会话。

---

## 现在在做什么

项目已完成 Phase 12 能力扩展（tau coverage），刚结束一轮 harness bug 修复（eval pass rate 72.8% → 79.5%）。当前焦点：project-brain 文档骨架初始化 + 后续 eval pass rate 优化。

## 下一步

1. 完成 project-brain 初始化（PROJECT/MAP/STATUS/DECISIONS 首版填写）
2. 审查 `brain/MAP.md` 第 5 节 topic 文档索引——需要从 `docs/` 下提取核心设计文档并建立 topic 摘要
3. 全量 eval pass rate 从 79.5% 继续提升（目标 >85%）
4. 考虑补齐 `modify_pending_order_payment` 写操作支持（当前 7 种写操作中唯一未覆盖的）

## 卡点 / 待确认

- 无硬阻塞。`DEEPSEEK_API_KEY` 已配置，项目可正常运行。

## 未提交改动

- `CLAUDE.md` — 已修改（合并 project-brain 中文协议）
- `brain/` — 新增目录（project-brain 骨架，首版内容已填写）
- `.cursorrules`、`AGENTS.md`、`.github/copilot-instructions.md` — 新增（AI 适配器）
- 建议单独 commit：`chore: 初始化 project-brain 文档骨架`

## 最近这次会话做了什么

- 从缓存 project-brain 运行 scaffold（`--lang zh`），创建 `brain/` + AI 适配器
- 合并中文 brain 阅读协议到 `CLAUDE.md`（保留原有架构文档）
- 填写 PROJECT.md / MAP.md / STATUS.md / DECISIONS.md 首版内容
- 运行 doctor.sh 体检，确认骨架完整
