"""Version-pinned deterministic PDFs. Rendering never calls a model or the web."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import RLock
from typing import Literal
from xml.sax.saxutils import escape

from pydantic import Field
from job_agent.schemas import StrictModel
from job_agent.resume_workspace.repository import WorkspaceConflict, WorkspaceNotFound

RENDERER_VERSION = 'reportlab-noto-v3-2'
_FONT_LOCK = RLock()


class PDFRequest(StrictModel):
    expected_content_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    template: Literal['classic', 'compact'] = 'classic'


def render_pdf(version, template: str) -> bytes:
    """Subset-embedded OFL Chinese font; text remains selectable and portable.

    No original source, reviewer rubric, hashes or internal provenance are printed
    into the applicant's resume. Metadata pins the immutable version separately.
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable

    if template not in ('classic', 'compact'):
        raise WorkspaceConflict('unknown_pdf_template')
    if sum(len(f.text) for f in version.document.facts()) > 200_000:
        raise WorkspaceConflict('pdf_content_limit')
    # Font registration is global in ReportLab, but no private font/data is global.
    with _FONT_LOCK:
        if 'JobAgentNoto' not in pdfmetrics.getRegisteredFontNames():
            font_path = Path(__file__).parent / 'assets/NotoSansSC.ttf'
            if not font_path.is_file():
                raise WorkspaceConflict('pdf_font_asset_missing')
            pdfmetrics.registerFont(TTFont('JobAgentNoto', str(font_path)))
    compact = template == 'compact'
    accent = colors.HexColor('#173f50' if compact else '#26372c')
    body = ParagraphStyle('body', fontName='JobAgentNoto', fontSize=10 if compact else 11,
                          leading=15 if compact else 17, wordWrap='CJK', spaceAfter=5)
    heading = ParagraphStyle('section', parent=body, fontSize=13, textColor=accent,
                             spaceBefore=13, spaceAfter=7, keepWithNext=True)
    title = ParagraphStyle('name', parent=body, fontSize=24, leading=30, spaceAfter=10,
                           alignment=TA_CENTER if compact else 0)
    sub = ParagraphStyle('entry', parent=body, fontSize=11, keepWithNext=True,
                         spaceBefore=5, textColor=accent)
    story = []
    def p(text, style=body):
        # Escape markup instead of interpreting applicant-provided tags/URLs.
        return Paragraph(escape(str(text)).replace('\n', '<br/>'), style)
    def texts(items):
        return '  |  '.join(x.text for x in items if x is not None)
    d = version.document
    story.append(p(d.personal.name.text, title))
    contact = [d.personal.email, d.personal.phone, d.personal.location, *d.personal.links]
    if any(contact):
        story.append(p(texts(contact)))
    story.append(HRFlowable(width='100%', thickness=1, color=accent))
    def section(label):
        story.append(p(label, heading))
    if d.summary:
        section('个人简介')
        story.extend(p(f.text) for f in d.summary)
    for label, items, names, bullets in (
        ('教育经历', d.education, ('school', 'degree', 'major', 'period'), 'highlights'),
        ('工作与实习', d.experience, ('organization', 'role', 'period'), 'bullets'),
        ('项目经历', d.projects, ('name', 'role', 'period'), 'bullets'),
    ):
        if not items:
            continue
        section(label)
        for item in items:
            story.append(p(texts([getattr(item, name) for name in names]), sub))
            story.extend(p('• ' + f.text) for f in getattr(item, bullets))
    if d.skills:
        section('技能')
        story.extend(p(f.text) for f in d.skills)
    buffer = BytesIO()
    margin = 36 if compact else 48
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=margin, rightMargin=margin,
                            topMargin=margin, bottomMargin=42, title=d.personal.name.text,
                            author='Job Agent', subject=f'{version.version_id}:{version.content_hash}')
    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont('JobAgentNoto', 8)
        canvas.setFillColor(colors.HexColor('#64736d'))
        canvas.drawRightString(A4[0]-margin, 22, str(document.page))
        canvas.restoreState()
    def invariant_canvas(*args, **kwargs):
        kwargs['invariant'] = 1
        return Canvas(*args, **kwargs)
    doc.build(story, onFirstPage=footer, onLaterPages=footer, canvasmaker=invariant_canvas)
    return buffer.getvalue()


class PDFRepository:
    def __init__(self, workspace):
        self.workspace = workspace
        with workspace._connection(write=True) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS rw_pdf_exports (
                export_id TEXT PRIMARY KEY,
                version_id TEXT NOT NULL REFERENCES rw_versions(version_id) ON DELETE CASCADE,
                template TEXT NOT NULL, renderer TEXT NOT NULL, content_hash TEXT NOT NULL,
                pdf_hash TEXT NOT NULL, pdf_bytes BLOB NOT NULL,
                UNIQUE(version_id, template, renderer))''')

    def export(self, owner, resume_id, version_id, request: PDFRequest):
        version = self.workspace.get_version(owner, resume_id, version_id)
        if version.content_hash != request.expected_content_hash:
            raise WorkspaceConflict('pdf_version_changed')
        if not version.confirmed_at:
            raise WorkspaceConflict('pdf_confirmation_required')
        export_id = 'pdf-' + sha256(f'{version_id}:{request.template}:{RENDERER_VERSION}'.encode()).hexdigest()[:32]
        with self.workspace._connection() as db:
            existing = db.execute('SELECT * FROM rw_pdf_exports WHERE export_id=?', (export_id,)).fetchone()
        if existing is None:
            data = render_pdf(version, request.template)
            with self.workspace._connection(write=True) as db:
                self.workspace._resume(db, owner, resume_id)
                self.workspace._version(db, resume_id, version_id)
                db.execute('INSERT OR IGNORE INTO rw_pdf_exports VALUES (?,?,?,?,?,?,?)',
                           (export_id, version_id, request.template, RENDERER_VERSION,
                            version.content_hash, sha256(data).hexdigest(), data))
        return self.metadata(owner, export_id)

    def _get(self, db, owner, export_id):
        row = db.execute('''SELECT e.*,v.resume_id FROM rw_pdf_exports e
            JOIN rw_versions v ON e.version_id=v.version_id JOIN rw_resumes r ON r.resume_id=v.resume_id
            WHERE e.export_id=? AND r.owner_id=?''', (export_id, owner)).fetchone()
        if row is None:
            raise WorkspaceNotFound('pdf_not_found')
        version = self.workspace._version(db, row['resume_id'], row['version_id'])
        self.workspace._validate_document(db, owner, version.document)
        if (row['content_hash'] != version.content_hash or not version.confirmed_at
                or sha256(row['pdf_bytes']).hexdigest() != row['pdf_hash']):
            raise WorkspaceConflict('pdf_integrity_failed')
        return row

    def metadata(self, owner, export_id):
        with self.workspace._connection() as db:
            row = self._get(db, owner, export_id)
            return {k:row[k] for k in ('export_id','resume_id','version_id','template','renderer','content_hash','pdf_hash')}

    def download(self, owner, export_id):
        with self.workspace._connection() as db:
            return bytes(self._get(db, owner, export_id)['pdf_bytes'])

    def list(self, owner, resume_id):
        with self.workspace._connection() as db:
            self.workspace._resume(db, owner, resume_id)
            ids = [r[0] for r in db.execute('''SELECT e.export_id FROM rw_pdf_exports e
                JOIN rw_versions v ON e.version_id=v.version_id WHERE v.resume_id=?
                ORDER BY v.sequence DESC,e.template''', (resume_id,))]
        return [self.metadata(owner, key) for key in ids]


def install_pdf_routes(app, workspace, owner):
    from fastapi import Depends, Response
    store = PDFRepository(workspace)

    @app.post('/api/v2/resumes/{resume_id}/versions/{version_id}/pdf', status_code=201)
    def export(resume_id: str, version_id: str, request: PDFRequest, user: str = Depends(owner)):
        return store.export(user, resume_id, version_id, request)

    @app.get('/api/v2/resumes/{resume_id}/pdfs')
    def history(resume_id: str, user: str = Depends(owner)):
        return store.list(user, resume_id)

    @app.get('/api/v2/pdfs/{export_id}')
    def download(export_id: str, user: str = Depends(owner)):
        return Response(store.download(user, export_id), media_type='application/pdf', headers={
            'Content-Disposition':f'inline; filename="resume-{export_id}.pdf"'})
