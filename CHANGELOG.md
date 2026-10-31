# CHANGELOG

## 未发布 — 2026-11-01

仓库级补充。**技能行为不变，但包体变了**，这两件事要分开说：

- **技能行为不变**：`SKILL.md`、`references/`、`templates/`、`scripts/` 逐字节未动，执行逻辑与 2.1.0 完全一致。
- **包体变了**：`CHANGELOG.md` 与 `README.md` 本身也在上传包内（官方规范把这两个文件列入包），本段一加，包就从 9 文件 40782 B 变成 42640 B。**平台正在审核的是 40782 B 那个版本**，两者差异仅限这两个文档文件。

技能版本号保持 2.1.0，因为该版本已在平台提交审核中；此时改版本号会让线上包与仓库对不上，改文档则不改变已提交的内容。若将来要重新提交，应以仓库当前状态打新包，并视作一次版本变更。

### 新增

- **`experts/signal-decoder/`**：专家（Expert）包，同一方法论的另一种交付形态。技能是工具，专家是入口——`defaultInitPrompt` 与三条 `quickPrompts` 把"我该问什么"也替用户解决了。此前该包只存在于本地工作目录，仓库里没有，等于这一形态没有版本管理。
- **`tools/validate_expert.py`**：专家包校验器，零第三方依赖。检查 16 个必填字段、name/plugin/agentName 三者一致、`displayDescription.zh` 中文 40-50 字、`defaultInitPrompt` 与 `quickPrompts[0]` 中英双语一致、tags 与 quickPrompts 各 3 个、头像 512×512 且 ≤500KB、agent frontmatter 四必填、无硬编码密钥、无 BOM/CRLF。

### 修复

- **头像尺寸校验在无 Pillow 环境下形同虚设**：原实现 `try: from PIL import Image ... except ImportError: r.warn("未安装 Pillow，跳过头像尺寸校验")`。CI 上不保证装得上 Pillow，所以"512×512"这条官方硬约束在流水线上从来没有被检查过——换一张 128×128 的图照样全绿。已改为 PNG 走零依赖路径（直接读 IHDR 前 24 字节取宽高），只有 JPG 才需要 Pillow。变异测试：把头像换成 128×128 → `[ERROR] 头像尺寸必须为 512x512，当前 128x128`，退出码 1。

### 变更

- **CI 打包步骤新增 `experts`、`tools` 到 `skip_dirs`**。这两个目录是仓库资产，进包会触发 `subs <= {references,scripts,templates}` 断言失败，也会让平台解析报「非官方子目录」。本地模拟 CI 打包已验证：仍 9 文件、内容与仓库当前源码一致。
- **CI 新增 `Validate expert package` 步骤**，在编码检查之前跑 `python tools/validate_expert.py experts/signal-decoder`。

## 2.1.0 — 2026-10-30

### Added
- 新增材料性质字段 `meta.material_nature`（problem_oriented / declarative），在分析入口区分问题导向材料与价值宣示材料。
- 校验器新增材料性质门控：declarative 材料置信度只能为 low，配 medium/high 直接报错；与既有 low 门控形成两层拦截。
- SKILL.md 新增收敛的澄清路由：处境缺失时结构化追问，最多 2 轮，仍无法确认则按 bystander 处理并降为 low。
- analysis-rubric、methodology、report-template 同步材料性质判定口径与填写位置。

### Changed
- 第二步「倡导主体有什么动机」改为「在什么背景下发出倡导」，与不做动机指控的边界保持一致。
- description 触发词「解读这条新闻」改为「解读这份材料」，避免在技能定义字段出现时政类措辞。

### 破坏性变更
- meta 新增必填字段 material_nature，2.0.0 生成的 JSON 需补该字段后才能通过校验。

## 2.0.0 — 2026-10-30

从「Prompt 集合」重构为「可维护的 Agent 技能项目」。

### 破坏性变更

- **分析对象变更**：从"媒体叙事解构 + 政策分析"收窄为"商业/职场公开信息拆解"。不再做政治立场判断、政策优劣评价、个体 vs 系统对抗框架。原因见 README「为什么不是新闻评论」。
- **输出格式变更**：六段式章节名调整（原「叙事链条与被省略的代价」→「制度安排与未出现的成本项」，原「框架选择」→「表述取舍」）。原格式的报告不再兼容。
- **信号强度分档变更**：原三档（建议/要求/强制）改为四档 L1–L4（L1 建议 / L2 引导 / L3 要求 / L4 强制），新增 L2。
- **缺口时间属性**：原两档（周期性/结构性）改为三档（周期性/结构性/过渡性）。这是最容易亏钱的一步，必须单列。
- **角色分类**：原三类（受益方/成本承担方/旁观方）改为四类，新增「中介方」。
- **`signals[].verb` 取消枚举**：2.0 之前要求 verb 必须是 10 个预设词之一。真实文本的规范性动词远超可穷举范围，枚举会误杀合法输入，改为 `minLength: 1` 的自由文本。

### 新增

- `schema/report.schema.json`（2.0 初始版本放在 `schema/`，2.0.0 发布前并入 `templates/`）：报告 JSON 结构契约，draft-07。
- `scripts/validate_report.py`：零第三方依赖的报告校验器。检查必填字段、枚举、最小长度、**真实日历日期**、矩阵四格完整性、**三道门槛完整性**、止损三要素、置信度门控、反废话黑名单。放在 `scripts/` 而非自定义目录，是为了让它随包上传——否则 SKILL.md 里"输出 JSON 后必须跑校验"在用户机器上是死链。
- `examples/`：两个完整示例报告，覆盖政策类（medium 置信度）与平台规则类（high 置信度）。
- `references/methodology.md`：方法论理论推导，与原版差异对照。
- `.github/workflows/validate.yml`：CI 三件套——示例报告校验、frontmatter 校验、编码校验、打包校验。

### 修复

- **日期校验形同虚设**：第一版只用正则 `^\d{4}-\d{2}-\d{2}$`，`2026-13-45` 能通过。README 里写了"会被拒"但实际没有。已补 `datetime.date.fromisoformat` 做真实日历校验，并用变异测试验证。
- **门槛校验形同虚设**：第一版允许只填一道门槛，`barriers` 字段形同虚设。已改为强制三档齐全（qualification / capability / scale），缺任何一档报错。
- **反废话一刀切误伤**：第一版所有黑名单都报 ERROR，示例报告里"数据赋能"被误杀——"赋能"在描述技术作用时是正常用法。已拆成 ERROR（和稀泥表述）与 WARN（空话形容词）两级。
- **非官方子目录风险**：第一版把方法论放 `docs/`、schema 放 `schema/`，打包校验时报「非官方子目录，可能被忽略或导致解析失败」。已全部并入 `references/` 与 `templates/`。
- **校验器输出被误读为"结论可靠"**：校验器只检查形式（结构、枚举、长度、日期真实性、黑名单），但输出只有一行「结论: 通过」，容易被当成分析质量的背书。已在每次运行的结尾固定打印边界声明，明确「不检查结论是否正确」。这条声明对通过和不通过的报告都打印——通过时更需要提醒。
- **打包脚本把仓库资产打进上传包**：第一版 `build_skill_zip.py` 排除隐藏文件但放行 `examples/`、`tools/`、`.github/`，导致上传包里出现官方不认可的子目录。已改为读 `.skillignore`（缺省时用内置排除表），并在打包后校验顶层目录唯一性。
- **孤儿文件检测对 `scripts/` 失明**：`validate_skill.py` 只识别 `references/*.md` 与 `templates/*` 两类引用，`scripts/*.py` 一律被判成孤儿，造成假警告。已补 `scripts/*.{py,js,sh}` 引用识别——引用存在性报 ERROR，纯孤儿仍报 WARN。两个方向都有变异测试验证。

### 移除

- 「宏大叙事」「个体 vs 系统」「叙事免疫」「退出选项 Plan B」等原版概念。不是因为这些概念没价值，而是因为它们属于评论写作，不属于可交付的商业分析。

---

## 1.0.0 — 2026-05-25

原始版本，见 [news-analysis-prompt](https://github.com/youcare7/news-analysis-prompt)。

形态为 Prompt 集合 + 示例输出，无 schema、无校验、无 CI。定位是「深度新闻分析师 + 个体策略顾问」。
