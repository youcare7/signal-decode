#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Signal Decode 报告校验器

依据 templates/report.schema.json 做结构化校验，但**不依赖 jsonschema 库**
（目标运行环境常无该依赖）。因此本脚本手写校验逻辑，覆盖：

  - 必填字段存在性
  - 枚举值合法性
  - 字符串最小长度（防止"提升核心竞争力"这类废话）
  - 数组最小条目数（防止矩阵缺格、止损缺失）
  - 日期格式
  - 反废话检测：命中黑名单表述直接判不通过

用法:
    python validate_report.py <report.json> [schema.json]

退出码: 0 = 通过；1 = 不通过
"""
import sys
import os
import json
import re
import datetime

# 和稀泥表述：命中即 ERROR。这类词让报告失去可操作性。
BANNED_PHRASES = [
    "综合来看机遇与挑战并存",
    "机遇与挑战并存",
    "提升核心竞争力",
    "把握机遇",
    "迎接挑战",
    "全面提升",
    "具体情况具体分析",
    "有待进一步观察",
]

# 空话形容词：命中只 WARN。单独出现多为废话，但在解释性语境中可能合法，
# 因此不硬拦，只提示改写为具体表述。
VAGUE_PHRASES = [
    "赋能",
    "全方位",
    "多维度",
    "专业高效",
    "值得关注",
    "值得期待",
    "高度重视",
]

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

ENUMS = {
    "doc_type": {"policy", "corporate_notice", "platform_rule", "industry_report", "media_release"},
    "source_grade": {"high", "medium", "low"},
    "material_nature": {"problem_oriented", "declarative"},
    "strength": {"L1-suggest", "L2-guide", "L3-require", "L4-mandate"},
    "gap_type": {"supply_shortage", "cost_too_high", "information_asymmetry",
                 "trust_deficit", "capability_gap", "institutional_void"},
    "temporality": {"cyclical", "structural", "transitional"},
    "role": {"beneficiary", "cost_bearer", "intermediary", "bystander"},
    "barrier_kind": {"qualification", "capability", "scale"},
    "stop_action": {"stop", "pivot", "scale"},
    "confidence": {"high", "medium", "low"},
}


class V:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.infos = []

    def err(self, p, m):
        self.errors.append("%s: %s" % (p, m))

    def warn(self, p, m):
        self.warnings.append("%s: %s" % (p, m))

    def info(self, m):
        self.infos.append(m)

    def req(self, obj, key, path):
        if key not in obj:
            self.err(path, "缺少必填字段 %r" % key)
            return False
        return True

    def enum(self, obj, key, path, enum_key):
        v = obj.get(key)
        if v is None:
            return
        allowed = ENUMS[enum_key]
        if v not in allowed:
            self.err(path, "%s=%r 不在允许值 %s 内" % (key, v, sorted(allowed)))

    def minlen(self, obj, key, path, n):
        v = obj.get(key)
        if v is None:
            return
        if not isinstance(v, str):
            self.err(path, "%s 必须是字符串" % key)
            return
        if len(v.strip()) < n:
            self.err(path, "%s 长度 %d < 要求 %d，疑似废话：%r" % (key, len(v.strip()), n, v))

    def date(self, obj, key, path, nullable=False):
        if key not in obj:
            return
        v = obj[key]
        if v is None:
            if not nullable:
                self.err(path, "%s 不能为 null" % key)
            return
        if not DATE_RE.match(str(v)):
            self.err(path, "%s=%r 不是 YYYY-MM-DD 格式" % (key, v))
            return
        # 正则只保证形如 YYYY-MM-DD，2026-13-45 也能过。这里补真实日历校验。
        try:
            datetime.date.fromisoformat(str(v))
        except ValueError:
            self.err(path, "%s=%r 不是真实存在的日期" % (key, v))

    def minitems(self, obj, key, path, n):
        v = obj.get(key)
        if not isinstance(v, list):
            self.err(path, "%s 必须是数组" % key)
            return
        if len(v) < n:
            self.err(path, "%s 至少需要 %d 项，当前 %d 项" % (key, n, len(v)))


def check_banned(v, data, path="$"):
    """递归扫描所有字符串：和稀泥表述报 ERROR，空话形容词报 WARN。"""
    if isinstance(data, dict):
        for k, val in data.items():
            check_banned(v, val, "%s.%s" % (path, k))
    elif isinstance(data, list):
        for i, val in enumerate(data):
            check_banned(v, val, "%s[%d]" % (path, i))
    elif isinstance(data, str):
        for bad in BANNED_PHRASES:
            if bad in data:
                v.err(path, "命中反废话黑名单：%r" % bad)
        for vague in VAGUE_PHRASES:
            if vague in data:
                v.warn(path, "含空话形容词 %r，建议改为具体表述" % vague)


def validate_matrix_cell(v, cell, path):
    if not isinstance(cell, dict):
        v.err(path, "矩阵格必须是对象")
        return
    for f, n in (("content", 15), ("evidence", 15), ("barrier", 5)):
        if not v.req(cell, f, path):
            continue
        v.minlen(cell, f, path, n)


def validate_action(v, a, path):
    if not isinstance(a, dict):
        v.err(path, "行动必须是对象")
        return
    for f, n in (("what", 10), ("when", 3), ("verifiable", 10)):
        if not v.req(a, f, path):
            continue
        v.minlen(a, f, path, n)


def main():
    if len(sys.argv) < 2:
        print("用法: python validate_report.py <report.json>")
        return 2

    fp = sys.argv[1]
    if not os.path.isfile(fp):
        print("文件不存在: %s" % fp)
        return 2

    raw = open(fp, "rb").read()
    if raw.startswith(b"\xef\xbb\xbf"):
        print("错误: 文件含 BOM，请去掉后重试")
        return 1

    try:
        d = json.loads(raw.decode("utf-8"))
    except Exception as e:
        print("错误: 不是合法 JSON: %s" % e)
        return 1

    v = V()

    # ---------- meta ----------
    if v.req(d, "meta", "$"):
        m = d["meta"]
        for f in ("source", "publisher", "publish_date", "doc_type", "source_grade", "material_nature"):
            v.req(m, f, "$.meta")
        v.minlen(m, "source", "$.meta", 1)
        v.minlen(m, "publisher", "$.meta", 1)
        v.date(m, "publish_date", "$.meta")
        v.date(m, "effective_date", "$.meta", nullable=True)
        v.enum(m, "doc_type", "$.meta", "doc_type")
        v.enum(m, "source_grade", "$.meta", "source_grade")
        v.enum(m, "material_nature", "$.meta", "material_nature")

    # ---------- signals ----------
    if v.req(d, "signals", "$"):
        sigs = d["signals"]
        if not isinstance(sigs, list) or not sigs:
            v.err("$.signals", "至少需要 1 条倡导信号")
        else:
            for i, s in enumerate(sigs):
                p = "$.signals[%d]" % i
                for f in ("quote", "verb", "strength", "target"):
                    v.req(s, f, p)
                v.minlen(s, "quote", p, 4)
                v.minlen(s, "target", p, 1)
                v.minlen(s, "verb", p, 1)
                v.enum(s, "strength", p, "strength")

    # ---------- gap ----------
    if v.req(d, "gap", "$"):
        g = d["gap"]
        for f in ("type", "reasoning", "temporality"):
            v.req(g, f, "$.gap")
        v.enum(g, "type", "$.gap", "gap_type")
        v.enum(g, "temporality", "$.gap", "temporality")
        v.minlen(g, "reasoning", "$.gap", 30)

    # ---------- position ----------
    if v.req(d, "position", "$"):
        p = d["position"]
        for f in ("role", "direct_impact"):
            v.req(p, f, "$.position")
        v.enum(p, "role", "$.position", "role")
        v.minlen(p, "direct_impact", "$.position", 20)
        bars = p.get("barriers")
        if isinstance(bars, list):
            seen = set()
            for i, b in enumerate(bars):
                bp = "$.position.barriers[%d]" % i
                for f in ("kind", "passed", "note"):
                    v.req(b, f, bp)
                v.enum(b, "kind", bp, "barrier_kind")
                if not isinstance(b.get("passed"), bool):
                    v.err(bp, "passed 必须是布尔值")
                v.minlen(b, "note", bp, 5)
                if b.get("kind"):
                    seen.add(b["kind"])
            # 三道门槛（资质/能力/规模）必须都检验过，只写一道等于没做门槛判断
            missing = {"qualification", "capability", "scale"} - seen
            if missing:
                v.err("$.position.barriers", "三道门槛未检验完整，缺少: %s" % ", ".join(sorted(missing)))
        elif bars is not None:
            v.err("$.position", "barriers 必须是数组")

    # ---------- matrix ----------
    if v.req(d, "matrix", "$"):
        mx = d["matrix"]
        for cell in ("direct_opportunity", "hidden_opportunity", "explicit_risk", "implicit_risk"):
            if not v.req(mx, cell, "$.matrix"):
                continue
            validate_matrix_cell(v, mx[cell], "$.matrix.%s" % cell)

    # ---------- actions ----------
    if v.req(d, "actions", "$"):
        a = d["actions"]
        for f in ("immediate", "quarter", "annual", "stop_loss"):
            v.req(a, f, "$.actions")
        for f in ("immediate", "quarter", "annual"):
            if f in a and isinstance(a[f], list):
                for i, act in enumerate(a[f]):
                    validate_action(v, act, "$.actions.%s[%d]" % (f, i))
        v.minitems(a, "immediate", "$.actions", 1)
        v.minitems(a, "stop_loss", "$.actions", 1)

        sl = a.get("stop_loss")
        if isinstance(sl, list):
            for i, s in enumerate(sl):
                p = "$.actions.stop_loss[%d]" % i
                for f in ("metric", "threshold", "action"):
                    v.req(s, f, p)
                v.minlen(s, "metric", p, 2)
                v.minlen(s, "threshold", p, 2)
                v.enum(s, "action", p, "stop_action")

        ww = a.get("watch_window")
        if isinstance(ww, list) and len(ww) > 3:
            v.err("$.actions.watch_window", "最多 3 项，当前 %d 项" % len(ww))

    # ---------- confidence ----------
    if v.req(d, "confidence", "$"):
        c = d["confidence"]
        for f in ("level", "weakest_link", "falsifier"):
            v.req(c, f, "$.confidence")
        v.enum(c, "level", "$.confidence", "confidence")
        v.minlen(c, "weakest_link", "$.confidence", 20)
        v.minlen(c, "falsifier", "$.confidence", 15)

        # 置信度与行动清单的一致性门控
        lvl = c.get("level")

        # 材料性质门控：价值宣示材料无罚则、无责任主体、无量化考核，
        # 不承载真实成本转移，置信度不得高于 low，防止把口号当成市场缺口。
        meta = d.get("meta", {})
        if meta.get("material_nature") == "declarative" and lvl in ("medium", "high"):
            v.err("$.meta.material_nature",
                  "材料为 declarative（价值宣示，无罚则/责任主体/量化考核），置信度只能为 low，当前 level=%r" % lvl)

        if lvl == "low":
            acts = d.get("actions", {})
            if acts.get("quarter"):
                v.err("$", "置信度为 low 时，actions.quarter 必须为空（只允许给立即档）")
            if acts.get("annual"):
                v.err("$", "置信度为 low 时，actions.annual 必须为空（只允许给立即档）")

    # ---------- 反废话 ----------
    check_banned(v, d)

    # ---------- 报告 ----------
    print("=" * 62)
    print("Signal Decode 报告校验")
    print("文件: %s" % fp)
    print("=" * 62)

    if isinstance(d.get("signals"), list):
        v.info("倡导信号: %d 条" % len(d["signals"]))
        strengths = [s.get("strength") for s in d["signals"] if isinstance(s, dict)]
        v.info("信号强度分布: %s" % ", ".join(str(x) for x in strengths))
    if isinstance(d.get("gap"), dict):
        v.info("缺口类型: %s / 时间属性: %s" % (d["gap"].get("type"), d["gap"].get("temporality")))
    if isinstance(d.get("meta"), dict):
        v.info("材料性质: %s" % d["meta"].get("material_nature"))
    if isinstance(d.get("confidence"), dict):
        v.info("置信度: %s" % d["confidence"].get("level"))

    for m in v.infos:
        print("  [INFO] %s" % m)
    for m in v.warnings:
        print("  [WARN] %s" % m)
    for m in v.errors:
        print("  [ERROR] %s" % m)

    print("-" * 62)
    if v.errors:
        print("结论: 不通过 — %d 个错误, %d 个警告" % (len(v.errors), len(v.warnings)))
    else:
        print("结论: 通过 — 0 个错误, %d 个警告" % len(v.warnings))

    # 边界声明：必须每次打印，防止"通过校验"被误读为"结论可靠"
    print("")
    print("边界声明：本校验器只检查结构、枚举、长度、日期真实性与黑名单用语，")
    print("         **不检查结论是否正确**。字段填满不等于分析成立——")
    print("         缺口归类是否准确、门槛判定是否属实、行动是否真的可验证，")
    print("         都需要人自己判断。通过校验只说明这份报告能被机器读懂。")

    return 1 if v.errors else 0


if __name__ == "__main__":
    sys.exit(main())
