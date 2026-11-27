"""Bounded, extractive parsing for common resume text layouts.

This is a local heuristic, not a model or a guarantee of semantic accuracy.
Every value retains its original character range for the existing verifier.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from job_agent.resume_workspace.parsing_contracts import FieldCandidate, ParseCandidate


HEADINGS = {
    **dict.fromkeys(("教育经历", "教育背景", "教育信息", "education", "education background"), "education"),
    **dict.fromkeys(("工作经历", "工作经验", "实习经历", "实习经验", "工作与实习", "employment", "work experience", "experience"), "experience"),
    **dict.fromkeys(("项目经历", "项目经验", "科研项目", "projects", "project experience"), "projects"),
    **dict.fromkeys(("技能", "专业技能", "专业能力", "技能特长", "技术技能", "技术栈", "skills", "technical skills"), "skills"),
    **dict.fromkeys(("个人简介", "自我评价", "个人总结", "summary", "profile"), "summary"),
    **dict.fromkeys(("荣誉奖项", "获奖经历", "获奖情况", "校园经历", "证书", "兴趣爱好", "求职意向", "其他", "awards", "certifications", "interests"), "other"),
}
LABEL = re.compile(r"(姓名|name|邮箱|电子邮箱|e-?mail|电话|手机|联系电话|phone|城市|现居地|居住地|location)\s*[:：]\s*", re.I)
LABEL_KEYS = {"姓名": "name", "name": "name", "邮箱": "email", "电子邮箱": "email", "email": "email", "e-mail": "email",
              "电话": "phone", "手机": "phone", "联系电话": "phone", "phone": "phone", "城市": "location", "现居地": "location", "居住地": "location", "location": "location"}
EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d(?:[- ]?\d){8}(?!\d)")
DATE = r"(?:19|20)\d{2}(?:[./年-]\d{1,2}(?:月)?)?"
PERIOD = re.compile(rf"{DATE}\s*(?:至|到|[-—–~～])\s*(?:{DATE}|至今|现在|present|current)", re.I)
DEGREE = re.compile(r"博士研究生|硕士研究生|大学本科|博士|硕士|本科|学士|大专|专科|Ph\.?D\.?|Master(?:'s)?|Bachelor(?:'s)?", re.I)
SCHOOL = re.compile(r"[^\s|｜,，;；:：]+?(?:大学|学院|职业学校|中学)(?:[^\s|｜,，;；:：]*?分校)?")
ROLE = re.compile(r"(?:项目负责人|项目开发|独立开发|团队负责人|[A-Za-z\u4e00-\u9fff]*(?:实习生|工程师|开发者|负责人|研究助理|开发))$")
ACTION = re.compile(r"^(?:负责|参与|使用|基于|采用|实现|设计|开发了|搭建|完成|优化|主修|核心课程|成绩|绩点|GPA|项目(?:描述|背景|职责|成果)|技术栈|职责|成果|技术方案|工作内容|项目内容|负责内容)", re.I)
SURNAMES = "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛范彭郎鲁韦马苗方俞任袁柳鲍史唐费薛雷贺倪汤滕殷罗毕郝安常乐于傅皮卞齐康伍余元卜顾孟平黄和穆萧肖尹姚邵汪毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯管卢莫房裘缪解应宗丁宣邓洪包左石崔吉龚程陆翁荀羊惠甄曲封储靳焦柳侯秋仲宫宁仇栾甘厉戎祖武符刘景詹束龙叶黎白蒲鄂索赖卓谭池乔温庄晏柴瞿阎连习向古易廖耿曾关游权司上欧诸东方皇尉公慕司徒南"


@dataclass(frozen=True)
class Line:
    text: str
    start: int
    bullet: bool = False

    def part(self, start: int, end: int | None = None) -> Line:
        raw = self.text[start:end]
        return Line(raw.strip(), self.start + start + len(raw) - len(raw.lstrip()), self.bullet)


def _lines(text: str) -> list[Line]:
    lines = []
    offset = 0
    for raw in text.splitlines(keepends=True):
        stripped = raw.strip()
        pos = offset + len(raw) - len(raw.lstrip())
        marker = re.match(r"(?:[-•●▪·*]\s+|\d{1,2}[、.)](?!\d)\s*)", stripped)
        bullet = bool(marker)
        if marker:
            pos += marker.end()
            stripped = stripped[marker.end():].lstrip()
            pos = offset + raw.find(stripped) if stripped else pos
        lines.append(Line(stripped, pos, bullet))
        offset += len(raw)
    return lines


def _heading(line: Line) -> str | None:
    key = re.sub(r"^#{1,6}\s*", "", line.text).strip(" ：:【】[]")
    # PDF headings often put a space between each Chinese character.
    key = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", key).casefold()
    return HEADINGS.get(key)


class LocalExtractor:
    def __init__(self):
        self.fields: dict[str, FieldCandidate] = {}
        self.warnings: list[str] = []

    def add(self, path: str, line: Line):
        if line.text and path not in self.fields:
            self.fields[path] = FieldCandidate(path=path, exact_quote=line.text, start=line.start, end=line.start + len(line.text))

    def personal(self, lines: list[Line]):
        choices: dict[str, list[Line]] = {}
        def remember(key, value):
            if value.text:
                choices.setdefault(key, []).append(value)
        for line in lines:
            labels = list(LABEL.finditer(line.text))
            for i, match in enumerate(labels):
                key = LABEL_KEYS[match.group(1).lower()]
                end = labels[i + 1].start() if i + 1 < len(labels) else len(line.text)
                value = line.part(match.end(), end)
                stop = re.search(r"[|｜;；]|\s{2,}|\s+(?:性别|年龄|男|女)\b", value.text)
                if stop:
                    value = value.part(0, stop.start())
                remember(key, value)
            for key, pattern in (("email", EMAIL), ("phone", PHONE)):
                for match in pattern.finditer(line.text):
                    remember(key, line.part(match.start(), match.end()))
        for key, values in choices.items():
            # Conflicting identity/contact values stay empty instead of picking one.
            if len({v.text for v in values}) == 1:
                self.add("personal." + key, values[0])
            else:
                self.warnings.append(f"{ {'name':'姓名','email':'邮箱','phone':'电话','location':'城市'}[key]}有多个候选，未自动选择，请核对原文。")
        if "name" not in choices:
            names = []
            for line in [l for l in lines if l.text][:4]:
                first = re.split(r"[|｜]|\s{2,}", line.text)[0].strip()
                if (re.fullmatch(r"[\u4e00-\u9fff]{2,4}", first) and first[0] in SURNAMES
                        and not any(word in first for word in ("简历", "求职", "开发", "工程", "研究", "专业", "信息"))):
                    names.append(line.part(0, len(first)))
                elif re.fullmatch(r"[A-Z][a-z]+(?: [A-Z][a-z]+){1,3}", first) and not any(w in first.lower() for w in ("resume", "curriculum", "developer", "engineer", "student")):
                    names.append(line.part(0, len(first)))
            if len({n.text for n in names}) == 1:
                self.add("personal.name", names[0])

    def entries(self, section: str, lines: list[Line]):
        index = -1
        bullet = 0
        blank = False
        title_key = {"education": "school", "experience": "organization", "projects": "name"}[section]
        list_key = "highlights" if section == "education" else "bullets"
        for pos, line in enumerate(lines):
            if not line.text:
                blank = True
                continue
            if re.fullmatch(r"(?:第\s*)?\d+\s*(?:页|/\s*\d+)?", line.text):
                continue
            period = PERIOD.search(line.text)
            explicit = re.match(r"(?:项目名称|项目|学校|毕业院校|公司名称|公司|组织名称)\s*[:：]\s*", line.text)
            description = line.bullet or bool(ACTION.match(line.text))
            role_only = bool(ROLE.fullmatch(line.text))
            period_only = period and not line.text[:period.start()].strip() and not line.text[period.end():].strip()
            next_line = next((l for l in lines[pos + 1:] if l.text), None)
            followed_by_metadata = next_line and (PERIOD.fullmatch(next_line.text) or ROLE.fullmatch(next_line.text))
            title = (not description and not role_only and not period_only and (
                index < 0 or explicit or "|" in line.text or "｜" in line.text
                or (period and len(line.text) <= 120 and not re.search(r"[。；;]", line.text))
                or (section == "education" and SCHOOL.search(line.text))
                or (len(line.text) <= 60 and (blank or followed_by_metadata) and not re.search(r"[，。:：；;]", line.text))))
            if title:
                index += 1
                bullet = 0
                self.header(f"{section}.{index}", line.part(explicit.end()) if explicit else line, section, title_key)
            else:
                if index < 0:
                    index = 0  # An incomplete entry is safer than an invented name.
                prefix = f"{section}.{index}"
                if period_only and prefix + ".period" not in self.fields:
                    self.add(prefix + ".period", line)
                elif role_only and prefix + ".role" not in self.fields and section != "education":
                    self.add(prefix + ".role", line)
                else:
                    self.add(f"{prefix}.{list_key}.{bullet}", line)
                    bullet += 1
            blank = False

    def header(self, prefix: str, line: Line, section: str, title_key: str):
        # Keep explicit M2 pipe format compatible, including year-only periods.
        parts = [line.part(m.start(), m.end()) for m in re.finditer(r"[^|｜]+", line.text)]
        if len(parts) > 1:
            dated = next((p for p in parts if PERIOD.fullmatch(p.text) or re.fullmatch(r"(?:19|20)\d{2}", p.text)), None)
            if dated:
                self.add(prefix + ".period", dated)
            rest = [p for p in parts if p is not dated]
            if section == "education":
                school = next((p for p in rest if SCHOOL.search(p.text)), rest[0] if rest else None)
                degree = next((p for p in rest if p is not school and DEGREE.search(p.text)), None)
                major = next((p for p in rest if p is not school and p is not degree), None)
                for key, value in (("school", school), ("degree", degree), ("major", major)):
                    if value:
                        self.add(prefix + "." + key, value)
            elif rest:
                self.add(prefix + "." + title_key, rest[0])
                if len(rest) > 1:
                    self.add(prefix + ".role", rest[1])
            return
        occupied = []
        period = PERIOD.search(line.text)
        if period:
            self.add(prefix + ".period", line.part(period.start(), period.end()))
            occupied.append(period.span())
        if section == "education":
            school, degree = SCHOOL.search(line.text), DEGREE.search(line.text)
            for key, match in (("school", school), ("degree", degree)):
                if match:
                    self.add(prefix + "." + key, line.part(match.start(), match.end()))
                    occupied.append(match.span())
            remaining = self.remaining(line, occupied)
            if school and len(remaining) == 1:
                self.add(prefix + ".major", remaining[0])
            elif not school:
                self.add(prefix + ".school", remaining[0] if remaining else line)
            return
        remaining = self.remaining(line, occupied)
        if remaining:
            # Two or more layout spaces delimit columns; single spaces can be in a title.
            fragments = [part.part(m.start(), m.end()) for part in remaining for m in re.finditer(r"\S(?:.*?\S)?(?=\s{2,}|\t|$)", part.text)]
            role = next((v for v in fragments if ROLE.fullmatch(v.text)), None)
            titles = [v for v in fragments if v is not role]
            if titles:
                self.add(prefix + "." + title_key, titles[0])
            if role:
                self.add(prefix + ".role", role)

    @staticmethod
    def remaining(line: Line, occupied: list[tuple[int, int]]) -> list[Line]:
        result = []
        cursor = 0
        for start, end in sorted(occupied):
            if start >= cursor:
                value = line.part(cursor, start)
                if value.text:
                    result.append(value)
                cursor = end
        value = line.part(cursor)
        if value.text:
            result.append(value)
        return result

    def extract(self, text: str) -> tuple[ParseCandidate, list[str]]:
        groups: dict[str, list[Line]] = {}
        intro = []
        section = None
        for line in _lines(text):
            heading = _heading(line)
            if line.text.strip(" ：:") == "技术栈" and section in {"projects", "experience"}:
                heading = None  # Project context must not become personal skill assertions.
            if heading:
                section = heading
            elif section is None:
                intro.append(line)
            else:
                groups.setdefault(section, []).append(line)
        self.personal(intro)
        for section in ("education", "experience", "projects"):
            self.entries(section, groups.get(section, []))
        for section in ("summary", "skills"):
            index = 0
            for line in groups.get(section, []):
                # Keep proficiency/negation/context as a whole sentence, never turn
                # 'not familiar with X' into an affirmative standalone X skill.
                sentence = bool(re.search(r"熟悉|了解|掌握|精通|使用|不|未|不会|擅长|[。；;]|\b(?:not|familiar|proficient)\b", line.text, re.I))
                parts = [line] if section == "summary" or sentence else [line.part(m.start(), m.end()) for m in re.finditer(r"[^,，、;；|｜]+", line.text)]
                for part in parts:
                    if part.text:
                        self.add(f"{section}.{index}", part)
                        index += 1
        return ParseCandidate(fields=list(self.fields.values())), self.warnings


def extract_local(text: str) -> tuple[ParseCandidate, list[str]]:
    return LocalExtractor().extract(text)
