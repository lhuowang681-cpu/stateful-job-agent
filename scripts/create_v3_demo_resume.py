"""Create a selectable-text synthetic input PDF, not a private resume."""
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
ROOT=Path(__file__).resolve().parents[1]


def main():
    pdfmetrics.registerFont(TTFont('DemoNoto',str(ROOT/'src/job_agent/resume_workspace/assets/NotoSansSC.ttf')))
    dest=ROOT/'docs/demo/assets/synthetic-resume-source.pdf';dest.parent.mkdir(parents=True,exist_ok=True)
    c=canvas.Canvas(str(dest),pagesize=(595,842),invariant=1);c.setTitle('Synthetic resume input — no private data')
    lines=['姓名：演示同学','邮箱：demo@example.invalid','城市：北京','','教育经历',
        '示例大学 | 硕士 | 计算机技术 | 2024.09—2027.06','','项目经历',
        '求职资料管理工具 | 项目开发 | 2025.03—2025.06',
        '- 使用 Python 和 FastAPI 实现资料录入与查询接口。',
        '- 为接口编写回归测试，检查异常输入和重复提交。','','技能','Python、FastAPI、SQL、Git']
    c.setFont('DemoNoto',11)
    for i,line in enumerate(lines):c.drawString(48,790-i*25,line)
    c.save();print(dest)


if __name__=='__main__':main()
