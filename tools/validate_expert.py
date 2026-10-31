#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 专家（Expert）包上传前校验脚本

依据 open.workbuddy.cn/docs/expert 与 /docs/developer-agreement 校验：
  1. 目录结构：.codebuddy-plugin/plugin.json、avatars/、agents/、README.md
  2. plugin.json 必填字段齐全
  3. name / plugin / agentName 三者一致，且 name 为小写+连字符
  4. displayDescription.zh 中文字数在 40-50 之间（公约 2.2.3 + 官方硬约束）
  5. defaultInitPrompt 必须与 quickPrompts 第一条一致（中英都要一致）
  6. tags 固定 3 个、quickPrompts 固定 3 个
  7. 头像 PNG/JPG、512x512、<=500KB
  8. agents/*.md 存在且 frontmatter 必填字段齐全、name 与文件名一致
  9. 不得出现纯文字头像（本脚本只校验尺寸/体积/格式，纯文字靠人工确认）
 10. 全文无 BOM、无 CRLF（JSON 解析失败常见原因）

用法:
    python validate_expert.py <expert-dir>

退出码: 0 = 通过；1 = 存在 ERROR
"""
import sys
import os
import json
import re

REQUIRED_PLUGIN_FIELDS = [
    "name", "expertType", "version", "description", "author", "agents",
    "agentName", "displayName", "profession", "displayDescription",
    "avatar", "categoryId", "defaultInitPrompt", "plugin", "tags", "quickPrompts",
]

REQUIRED_AGENT_FIELDS = ["name", "description", "displayName", "profession"]

CATEGORY_IDS = {
    "01-ProductDesign", "02-Engineering", "03-GameSpatial", "04-DataAI",
    "05-MarketingGrowth", "06-ContentCreative", "07-SalesCommerce",
    "08-FinanceInvestment", "09-OperationsHR", "10-ProjectQuality",
    "11-SecurityCompliance", "12-IndustryConsultant", "13-TencentZone",
    "14-WorldWise", "15-Education",
}

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
BOM = b"\xef\xbb\xbf"


class Result:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.infos = []

    def err(self, m):
        self.errors.append(m)

    def warn(self, m):
        self.warnings.append(m)

    def info(self, m):
        self.infos.append(m)


def cjk_count(s):
    """统计中文字符数（不含标点、数字、字母）。"""
    return sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")


def zh_len_all(s):
    """统计中文字符 + 中文标点的总长度，作为上限参考。"""
    return len(s)


def check_bytes(path, r, rel):
    raw = open(path, "rb").read()
    if raw.startswith(BOM):
        r.err("%s 含 BOM，可能导致解析失败" % rel)
    if b"\r\n" in raw:
        r.warn("%s 使用 CRLF 换行，建议归一化为 LF" % rel)
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as e:
        r.err("%s 不是合法 UTF-8: %s" % (rel, e))


def parse_frontmatter(text, rel, r):
    """极简 YAML frontmatter 解析：只取顶层 key: value 与两空格缩进子键。"""
    if not text.startswith("---"):
        r.err("%s 缺少 frontmatter 起始 ---" % rel)
        return None, None
    end = text.find("\n---", 3)
    if end == -1:
        r.err("%s frontmatter 未闭合（缺少结束 ---）" % rel)
        return None, None
    block = text[3:end].strip("\n")
    body = text[end + 4:]

    data = {}
    cur_key = None
    for line in block.split("\n"):
        if not line.strip():
            continue
        if line.startswith("  ") and cur_key:
            sub = line.strip()
            if ":" in sub:
                k, v = sub.split(":", 1)
                if isinstance(data.get(cur_key), dict):
                    data[cur_key][k.strip()] = v.strip().strip('"').strip("'")
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip()
            cur_key = k
            if v == "":
                data[k] = {}
            else:
                data[k] = v.strip('"').strip("'")
    return data, body


def png_size(path):
    """零依赖读 PNG 尺寸。

    CI 里不保证装得上 Pillow，而「头像必须 512x512」是官方硬约束。
    如果 Pillow 缺失就只打一条 WARN 跳过，等于这条约束在 CI 上从来没有被检查过——
    于是有人换一张 128x128 的图，流水线照样全绿。这里直接读 IHDR 前 24 字节。
    返回 (w, h)；不是合法 PNG 时返回 None。
    """
    try:
        with open(path, "rb") as f:
            head = f.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    import struct
    return struct.unpack(">II", head[16:24])


def main():
    if len(sys.argv) < 2:
        print("用法: python validate_expert.py <expert-dir>")
        return 2

    root = os.path.abspath(sys.argv[1])
    if not os.path.isdir(root):
        print("目录不存在: %s" % root)
        return 2

    r = Result()
    top = os.path.basename(root)
    r.info("专家目录: %s" % top)

    # --- 结构 ---
    pj_path = os.path.join(root, ".codebuddy-plugin", "plugin.json")
    if not os.path.isfile(pj_path):
        r.err("缺少 .codebuddy-plugin/plugin.json")
        report(root, r)
        return 1
    check_bytes(pj_path, r, ".codebuddy-plugin/plugin.json")

    try:
        pj = json.loads(open(pj_path, "rb").read().decode("utf-8"))
    except Exception as e:
        r.err("plugin.json 不是合法 JSON: %s" % e)
        report(root, r)
        return 1

    # --- 必填字段 ---
    for f in REQUIRED_PLUGIN_FIELDS:
        if f not in pj or pj[f] in (None, "", [], {}):
            r.err("plugin.json 缺少必填字段: %s" % f)

    name = pj.get("name", "")
    if name:
        if not NAME_RE.match(name):
            r.err("name 必须是「小写字母/数字 + 连字符」格式，当前: %r" % name)
        if name != top:
            r.warn("name(%s) 与目录名(%s) 不一致，建议保持一致" % (name, top))
    if pj.get("plugin") and pj.get("plugin") != name:
        r.err("plugin(%s) 必须与 name(%s) 一致" % (pj.get("plugin"), name))

    if pj.get("expertType") not in ("agent", "team"):
        r.err("expertType 必须为 'agent' 或 'team'，当前: %r" % pj.get("expertType"))

    ver = str(pj.get("version", ""))
    if not re.match(r"^\d+\.\d+\.\d+", ver):
        r.err("version 必须是语义化版本（如 1.0.0），当前: %r" % ver)

    if pj.get("categoryId") and pj["categoryId"] not in CATEGORY_IDS:
        r.err("categoryId 不在官方 15 类中: %r" % pj["categoryId"])

    # --- 展示描述字数 ---
    dd = pj.get("displayDescription") or {}
    zh = (dd.get("zh") or "")
    n_cjk = cjk_count(zh)
    n_all = zh_len_all(zh)
    r.info("displayDescription.zh: 中文字符 %d 个 / 总长 %d 字符" % (n_cjk, n_all))
    if not (40 <= n_cjk <= 50):
        # 兼容按总长计数的口径
        if not (40 <= n_all <= 50):
            r.err("displayDescription.zh 中文字数须在 40-50 之间，"
                  "当前中文 %d 字 / 总长 %d 字符" % (n_cjk, n_all))
        else:
            r.warn("displayDescription.zh 按中文字符数(%d)不在 40-50，"
                   "按总长(%d)在范围内；平台口径未明示，建议调整到两种口径都合规" % (n_cjk, n_all))

    # --- tags / quickPrompts ---
    tags = pj.get("tags") or []
    if len(tags) != 3:
        r.err("tags 必须固定 3 个，当前 %d 个" % len(tags))
    for i, t in enumerate(tags):
        if not isinstance(t, dict) or "en" not in t or "zh" not in t:
            r.err("tags[%d] 必须是 {en, zh} 双语对象" % i)

    qp = pj.get("quickPrompts") or []
    if len(qp) != 3:
        r.err("quickPrompts 必须固定 3 个，当前 %d 个" % len(qp))
    for i, q in enumerate(qp):
        if not isinstance(q, dict) or "en" not in q or "zh" not in q:
            r.err("quickPrompts[%d] 必须是 {en, zh} 双语对象" % i)

    dip = pj.get("defaultInitPrompt") or {}
    if qp and isinstance(qp[0], dict):
        for lang in ("zh", "en"):
            a = (dip.get(lang) or "").strip()
            b = (qp[0].get(lang) or "").strip()
            if a != b:
                r.err("defaultInitPrompt.%s 必须与 quickPrompts[0].%s 完全一致\n"
                      "    当前 defaultInitPrompt: %r\n"
                      "    当前 quickPrompts[0]:   %r" % (lang, lang, a, b))

    # --- 头像 ---
    av_rel = pj.get("avatar") or ""
    if av_rel:
        av = os.path.join(root, av_rel.replace("/", os.sep))
        if not os.path.isfile(av):
            r.err("头像文件不存在: %s" % av_rel)
        else:
            ext = os.path.splitext(av)[1].lower()
            if ext not in (".png", ".jpg", ".jpeg"):
                r.err("头像格式必须为 PNG/JPG，当前: %s" % ext)
            size = os.path.getsize(av)
            if size > 500 * 1024:
                r.err("头像超过 500KB，当前 %.1f KB" % (size / 1024.0))
            else:
                r.info("头像体积: %.1f KB" % (size / 1024.0))
            # 先走零依赖路径：PNG 直接读 IHDR，JPG 才需要 Pillow。
            # 这样 CI 上即使没有 Pillow，512x512 这条硬约束也真的被检查。
            dims = None
            if ext == ".png":
                dims = png_size(av)
                if dims is None:
                    r.err("头像文件不是合法的 PNG（魔数或 IHDR 头不正确）")
            if dims is not None:
                w, h = dims
                r.info("头像尺寸: %dx%d（零依赖解析）" % (w, h))
                if (w, h) != (512, 512):
                    r.err("头像尺寸必须为 512x512，当前 %dx%d" % (w, h))
            elif ext in (".jpg", ".jpeg"):
                try:
                    from PIL import Image
                    with Image.open(av) as im:
                        w, h = im.size
                        r.info("头像尺寸: %dx%d" % (w, h))
                        if (w, h) != (512, 512):
                            r.err("头像尺寸必须为 512x512，当前 %dx%d" % (w, h))
                except ImportError:
                    r.warn("JPG 头像需要 Pillow 才能校验尺寸，当前未安装，已跳过")
            else:
                try:
                    from PIL import Image
                    with Image.open(av) as im:
                        w, h = im.size
                        r.info("头像尺寸: %dx%d" % (w, h))
                        if (w, h) != (512, 512):
                            r.err("头像尺寸必须为 512x512，当前 %dx%d" % (w, h))
                except ImportError:
                    r.warn("未安装 Pillow，跳过头像尺寸校验")

    # --- agents ---
    agents = pj.get("agents") or []
    if not agents:
        r.err("agents 不能为空")
    agent_name = pj.get("agentName") or ""
    found_main = False
    for a in agents:
        ap = os.path.join(root, a.replace("./", "").replace("/", os.sep))
        if not os.path.isfile(ap):
            r.err("Agent 定义文件不存在: %s" % a)
            continue
        check_bytes(ap, r, a)
        text = open(ap, "rb").read().decode("utf-8")
        fm, _ = parse_frontmatter(text, a, r)
        if fm is None:
            continue
        for f in REQUIRED_AGENT_FIELDS:
            if f not in fm or fm[f] in ("", {}, None):
                r.err("%s frontmatter 缺少必填字段: %s" % (a, f))
        base = os.path.splitext(os.path.basename(ap))[0]
        if fm.get("name") != base:
            r.err("%s frontmatter 的 name(%r) 必须与文件名(%r) 一致"
                  % (a, fm.get("name"), base))
        if base == agent_name:
            found_main = True
        for sub in ("displayName", "profession"):
            v = fm.get(sub)
            if not isinstance(v, dict):
                r.err("%s 的 %s 必须是 {en, zh} 双语子字段" % (a, sub))
            else:
                for lang in ("en", "zh"):
                    if not v.get(lang):
                        r.err("%s 的 %s.%s 不能为空" % (a, sub, lang))
    if agent_name and not found_main:
        r.err("agentName(%s) 在 agents/ 中找不到对应文件" % agent_name)

    # --- README ---
    if not os.path.isfile(os.path.join(root, "README.md")):
        r.warn("缺少 README.md（非必填，但官方基础结构包含）")

    # --- 禁止硬编码密钥 ---
    secret_re = re.compile(r"(sk-[A-Za-z0-9]{16,}|Bearer\s+[A-Za-z0-9\-_\.]{20,})")
    for dirpath, _, files in os.walk(root):
        for fn in files:
            fp = os.path.join(dirpath, fn)
            if os.path.splitext(fn)[1].lower() not in (".md", ".json", ".yaml", ".yml", ".txt"):
                continue
            try:
                txt = open(fp, "rb").read().decode("utf-8", "ignore")
            except Exception:
                continue
            if secret_re.search(txt):
                r.err("疑似硬编码密钥: %s" % os.path.relpath(fp, root))

    return report(root, r)


def report(root, r):
    print("=" * 62)
    print("WorkBuddy Expert 校验报告")
    print("目标: %s" % root)
    print("=" * 62)
    for m in r.infos:
        print("  [INFO] %s" % m)
    for m in r.warnings:
        print("  [WARN] %s" % m)
    for m in r.errors:
        print("  [ERROR] %s" % m)
    print("-" * 62)
    if r.errors:
        print("结论: 不通过 — %d 个错误, %d 个警告" % (len(r.errors), len(r.warnings)))
        return 1
    print("结论: 通过 — 0 个错误, %d 个警告" % len(r.warnings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
