# Retail Customer Support Agent — Landing Page Design Spec

> 完整前端设计规格，面向作品集展示。  
> 8 个 Section 的横向图片设计决策、布局锚点、配色、字体、背景策略。
>
> 本文件输出给：**图像生成 Agent**（Midjourney / DALL·E / Stable Diffusion）  
> 或 **前端开发者** 直接按此规格实现 HTML/CSS。

---

## 全局设计决策

| 维度 | 选择 |
|------|------|
| 产品定位 | 零售客服 LLM Agent 作品集 — 核心卖点：「7 层写安全护栏 + 全链路可审计 + 意图消歧」 |
| **Section 数量** | 8（完整 Landing Page） |
| **Hero Scale** | Mid Editorial — 产品优先，信任驱动 |
| **Theme Paradigm** | Deep Dark Mode — 炭黑/墨色基底 |
| **Primary Palette** | 主色: `#0f1117` (Ink 墨) · 表面: `#1a1d27` · 强调: `#e8993a` (Amber 暖金，零售温度) · 辅助: `#5b7ea3` (Steel Blue，信任感) |
| **Typography** | Satoshi-like clean grotesk (类 Inter / Geist，现代技术感) |
| **Narrative Spine** | Tool / Precision Instrument — 安全即工艺，7 层如 7 道精密加工程序 |
| **Second-Read Moment** | Vertical Rhythm Lines — 呼应 7 层护栏的纵深防御结构 |
| **Signature Components** | ① Pristine Gapless Bento Grid ② Vertical Rhythm Lines ③ Product UI Panel Stack ④ Oversized Metrics Strip |
| **Motion Language** | staggered float-up + parallax image drift |
| **Layout Variation** | 8 sections 使用 ≥5 种不同 Composition Anchor |
| **Background Variation** | 8 sections 使用 ≥4 种不同 Background Mode |
| **语言** | 中文（标题 + 短文案），代码标识符保留英文 |

---

## Section-by-Section 设计规格

### Section 1/8: Hero

| 属性 | 值 |
|------|----|
| **Composition Anchor** | Bottom-left text over background image |
| **Background Mode** | Full-bleed image with dark tonal overlay |
| **CTA** | Ghost outline button |
| **尺寸** | 16:9 |

**内容布局：**
```
┌────────────────────────────────────────────┐
│                                            │
│                                            │
│               [留白区域]                     │
│        (抽象零售场景影像/深色60% overlay)      │
│                                            │
│  ┌────────────────────────────┐             │
│  │ 写安全，不妥协              │             │
│  │ 零售客服 LLM Agent         │  ← 文字在   │
│  │ 7 层写护栏 · 全链路可审计   │     左下角   │
│  │                           │             │
│  │ [查看架构 ▸]  开源项目      │             │
│  │ DeepSeek-V4 · Python · React             │
│  └────────────────────────────┘             │
└────────────────────────────────────────────┘
```

**视觉特征：**
- 大面积留白在右上方
- 纵向细线暗示护栏结构（Vertical Rhythm Lines 首次出现）
- Amber `#e8993a` 强调色仅出现在 CTA hover 区域
- 背景影像：暗化处理的零售场景抽象意象（结账台、包裹扫描、库存货架）

---

### Section 2/8: Trust Bar

| 属性 | 值 |
|------|----|
| **Composition Anchor** | Centered statement |
| **Background Mode** | Pure solid with soft ambient gradient（墨 → 微深炭） |
| **CTA** | 无（纯信任展示） |
| **尺寸** | 16:10 |

**内容布局：**
```
┌────────────────────────────────────────────┐
│                                            │
│        7             14            100%     │
│     层写护栏       精选案例     可审计 Trace  │
│                                            │
│     [极大负空间，极度克制]                    │
│                                            │
└────────────────────────────────────────────┘
```

**视觉特征：**
- 3 列迷你指标，数字使用 Amber `#e8993a`
- 不使用 fake stats / 图标 / 装饰
- 大量负空间，与 Hero 的密度形成对比

---

### Section 3/8: Feature Grid

| 属性 | 值 |
|------|----|
| **Composition Anchor** | Top-left lead, support bottom-right |
| **Background Mode** | Solid surface with inline asset |
| **CTA** | Underlined inline link「深入了解架构 →」 |
| **尺寸** | 16:10 |

**内容布局：**
```
┌────────────────────────────────────────────┐
│  核心能力                                    │
│                                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ 🧠 意图   │  │ ✅ 显式   │  │ 🛡️ 纵深   │  │
│  │   消歧    │  │   确认   │  │   防御    │  │
│  │ LLM 理解  │  │ 用户    │  │ 7 层独立  │  │
│  │ 自然语言→ │  │ yes/no  │  │ 校验，   │  │
│  │   Action  │  │ 决定写入 │  │ deny-wins │  │
│  └──────────┘  └──────────┘  └──────────┘  │
│                                            │
│              深入了解架构 →                   │
└────────────────────────────────────────────┘
```

**视觉特征：**
- Gapless Bento Grid，卡片间 1px 分隔线（`#2a2d37`）
- 每个卡片包含 icon + 标题 + 一句说明
- 卡片底色 `#1a1d27`，比背景稍亮

---

### Section 4/8: Architecture Showcase

| 属性 | 值 |
|------|----|
| **Composition Anchor** | Centered low（图示在上部 60%，文字在下方） |
| **Background Mode** | Full-bleed image with tonal overlay |
| **CTA** | Ghost pill「阅读架构文档」 |
| **尺寸** | 16:9 |

**内容布局：**
```
┌────────────────────────────────────────────┐
│                                            │
│    user → pre-flight → AgentLoop →         │
│          ToolGateway → WriteActionGuard     │
│                    → DB                     │
│    [流程节点以悬浮卡片呈现]                    │
│                                            │
│  ────────────────────────────────────────  │
│  LLM 负责理解意图，代码负责安全边界            │
│             [阅读架构文档 ▸]                  │
└────────────────────────────────────────────┘
```

**视觉特征：**
- Product UI Panel Stack 组件
- 流程节点以悬浮卡片形式呈现（参考 Workbench Timeline 风格但更抽象）
- 深色代码/终端的抽象纹理作为背景
- 节点间用 Amber 箭头连接

---

### Section 5/8: Use Cases

| 属性 | 值 |
|------|----|
| **Composition Anchor** | Off-grid editorial offset（不对称拉出） |
| **Background Mode** | Editorial side-image (60/40) |
| **CTA** | Outline「在 Workbench 中体验 →」 |
| **尺寸** | 16:10 |

**内容布局：**
```
┌────────────────────────────────────────────┐
│  应用场景                    ┌────────────┐│
│                            │  零售场景    ││
│  🔐 身份认证                │  影像       ││
│   姓名+邮编 → 查订单         │            ││
│                            │            ││
│  ✅ 成功写操作               │            ││
│   取消/退货/换货/改支付       │            ││
│                            │            ││
│  🛡️ 护栏拦截                 │            ││
│   越权/跨品/余额不足          │            ││
│                            │            ││
│  📞 边界能力                 │            ││
│   转人工客服                  │            ││
│                            └────────────┘│
│    在 Workbench 中体验 →                   │
└────────────────────────────────────────────┘
```

**视觉特征：**
- Vertical Rhythm Lines 贯穿左侧案例列表
- 右侧 40% 为零售场景影像（风格与 Section 1 协调）
- 左侧案例列表按旅程分组，每组一行

---

### Section 6/8: Write Safety Deep Dive

| 属性 | 值 |
|------|----|
| **Composition Anchor** | Right-third caption + left-two-thirds visual |
| **Background Mode** | Subtle texture / grid（深色网格纹理） |
| **CTA** | Underlined inline「查看护栏源码 →」 |
| **尺寸** | 16:10 |

**内容布局：**
```
┌────────────────────────────────────────────┐
│                                            │
│  0  认证层     Authentication              │
│  ─────────────────────────────────────     │
│  1  显式确认   Explicit Confirmation  ★     │
│  ─────────────────────────────────────     │
│  2  所有权     Ownership                    │
│  ─────────────────────────────────────     │
│  3  先读后写   Read Before Write            │
│  ─────────────────────────────────────     │
│  4  策略合规   Policy Compliance   ★        │
│  ─────────────────────────────────────     │
│  5  资源锁     Resource Locks               │
│  ─────────────────────────────────────     │
│  6  幂等性     Idempotency                  │
│                                            │
│          查看护栏源码 →                       │
└────────────────────────────────────────────┘
```

**视觉特征：**
- 7 条水平细线对应 7 层（1px，`#2a2d37`）
- 左侧大号数字 `0`-`6`（使用 Amber）
- Amber 高亮 Layer 2（显式确认）和 Layer 5（策略合规）—— 用户最直接感知的两层
- 极度理性克制，暗示"精确"和"校准"

---

### Section 7/8: Eval & Metrics

| 属性 | 值 |
|------|----|
| **Composition Anchor** | Stacked center |
| **Background Mode** | Solid surface（比主背景稍亮的炭灰） |
| **CTA** | Ghost pill「查看完整 Eval 报告」 |
| **尺寸** | 16:10 |

**内容布局：**
```
┌────────────────────────────────────────────┐
│                                            │
│                                            │
│         1.000         1.000       5.91%     │
│        pass@1      db_accuracy  guard_block  │
│                                            │
│    30/30 通过 · 0 突变 · 0 工具错误           │
│                                            │
│            [查看完整 Eval 报告]               │
│                                            │
└────────────────────────────────────────────┘
```

**视觉特征：**
- Oversized Metrics Strip 风格
- 超大数字（64px+）+ 极小说明文字（11px）
- 强烈的尺度对比
- Amber 用于数字，Steel Blue 用于标签

---

### Section 8/8: CTA + Footer

| 属性 | 值 |
|------|----|
| **Composition Anchor** | Stacked center (ultra minimalist) |
| **Background Mode** | Color-blocked diptych（上半深墨、下半纯黑） |
| **CTA** | Oversized headline + tiny CTA hint |
| **尺寸** | 16:9 |

**内容布局：**
```
┌────────────────────────────────────────────┐
│  ┌─ 上半: #0f1117 ───────────────────────┐ │
│                                            │
│              准备好了吗？                     │
│                                            │
│  └────────────────────────────────────────┘ │
│  ┌─ 下半: #000000 ───────────────────────┐ │
│                                            │
│  克隆仓库，启动 Workbench，体验 7 层护栏     │
│  ┌────────────────────────────────────┐    │
│  │ git clone ... && uv run workbench  │    │
│  └────────────────────────────────────┘    │
│                                            │
│  © 2026 · MIT License · 开源项目            │
│  └────────────────────────────────────────┘ │
└────────────────────────────────────────────┘
```

**视觉特征：**
- Mini Minimalist 收束
- 唯一视觉元素是底部一行极小的代码块
- 代码块底色 `#1a1d27`，边框 `#2a2d37`

---

## 连续性校验清单

- [ ] 所有 Section 使用同一 Palette（Ink + Amber + Steel Blue）
- [ ] 同一 Typography 家族贯穿始终
- [ ] CTA 风格有变化但身份一致（ghost / outline / underlined / mini hint）
- [ ] **8 个 Section 使用了 ≥5 种不同 Composition Anchor**
- [ ] **8 个 Section 使用了 ≥4 种不同 Background Mode**
- [ ] 至少 1 个 full-bleed 背景（Section 1, 4）+ 至少 1 个 mini minimalist（Section 8）
- [ ] 无 AI slop：无紫色发光、无浮动球体、无 fake 仪表盘
- [ ] 无 left-text/right-image 重复出现
- [ ] 每张图为 16:9 或 16:10 横向图，一图一 section
- [ ] Narrative Spine（Precision Instrument）在 Section 6（7 层护栏）和 Section 4（架构流）中强烈体现
- [ ] Second-Read Moment（Vertical Rhythm Lines）出现在 Section 1 和 Section 5

---

## 生成说明

```bash
# 输出目录
artifacts/landing-page/
# 命名规则
section-01-hero.png
section-02-trust-bar.png
section-03-feature-grid.png
section-04-architecture.png
section-05-use-cases.png
section-06-safety-deep-dive.png
section-07-eval-metrics.png
section-08-cta-footer.png
```
