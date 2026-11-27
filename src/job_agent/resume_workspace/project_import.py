"""Pure bounded archive scanning. Imported projects are DATA, never executed."""
from __future__ import annotations
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
import re
import stat
import unicodedata
from zipfile import ZipFile, BadZipFile
from job_agent.resume_workspace.repository import WorkspaceConflict

MAX_ARCHIVE_BYTES=8*1024*1024
MAX_EXPANDED_BYTES=24*1024*1024
MAX_FILE_BYTES=256*1024
MAX_FILES=1200
ALLOWED_SUFFIXES={'.py','.js','.jsx','.ts','.tsx','.md','.txt','.sql','.toml','.json','.yaml','.yml','.css','.html','.ini'}
IGNORED_PARTS={'.git','.hg','.svn','.venv','venv','node_modules','__pycache__','.pytest_cache','dist','build','output','outputs','.codex','.aws','.ssh','coverage'}
SECRET_NAMES={'.env','id_rsa','id_ed25519','credentials','credentials.json','secrets.json','service-account.json','.npmrc','.pypirc'}
_CREDENTIAL=re.compile(r'''(?ix)(?:api[_-]?key|secret|password|access[_-]?token)\s*[:=]\s*["'][^\s"']{12,}["']|-----BEGIN\s+(?:RSA\s+|OPENSSH\s+|EC\s+)?PRIVATE\s+KEY-----''')


def checked_path(value: str) -> str:
    value=unicodedata.normalize('NFC',value)
    if not value or len(value)>240 or '\\' in value or re.search(r'[\x00-\x1f:<>"|?*]',value):
        raise WorkspaceConflict('unsafe_archive_path')
    path=PurePosixPath(value)
    if path.is_absolute() or any(x in ('','..','.') or x.endswith(('.', ' ')) for x in value.split('/')) or len(path.parts)>14:
        raise WorkspaceConflict('unsafe_archive_path')
    if any(re.fullmatch(r'(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?',p,re.I) for p in path.parts):
        raise WorkspaceConflict('unsafe_archive_path')
    return path.as_posix()


def excluded(path, text=None):
    parts=PurePosixPath(path.casefold()).parts
    name=parts[-1]
    return (any(p in IGNORED_PARTS for p in parts) or name in SECRET_NAMES
        or name.startswith('.env') or PurePosixPath(name).suffix in {'.pem','.key','.p12','.pfx','.sqlite','.db'}
        or 'private_key' in name or 'package-lock' in name or 'yarn.lock' in name
        or bool(text is not None and _CREDENTIAL.search(text)))


def scan_zip(data: bytes, *, strip_single_root=False):
    if not data or len(data)>MAX_ARCHIVE_BYTES:raise WorkspaceConflict('archive_upload_limit')
    files={};skipped=0;seen=set()
    try:
        with ZipFile(BytesIO(data)) as archive:
            infos=archive.infolist()
            if len(infos)>MAX_FILES or sum(x.file_size for x in infos)>MAX_EXPANDED_BYTES:
                raise WorkspaceConflict('archive_expansion_limit')
            for info in infos:
                if info.flag_bits&1:raise WorkspaceConflict('encrypted_archive_not_supported')
                mode=(info.external_attr>>16)&0xFFFF
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
                    raise WorkspaceConflict('archive_symlink_or_special_file')
                name=info.filename.rstrip('/') if info.is_dir() else info.filename
                path=checked_path(name)
                if path.casefold() in seen:raise WorkspaceConflict('archive_duplicate_path')
                seen.add(path.casefold())
                if info.is_dir():continue
                if excluded(path) or (PurePosixPath(path).suffix.casefold() not in ALLOWED_SUFFIXES and PurePosixPath(path).name.casefold() not in {'license','copying','notice'}):
                    skipped+=1;continue
                # Never decompress excluded binary/assets. Whole-archive expanded
                # size/count limits still cover them before this loop.
                if info.file_size>MAX_FILE_BYTES or info.file_size>max(1,info.compress_size)*200:
                    raise WorkspaceConflict('archive_file_limit')
                raw=archive.read(info)
                if b'\x00' in raw:skipped+=1;continue
                try:text=raw.decode('utf-8-sig')
                except UnicodeDecodeError:
                    try:text=raw.decode('gb18030')
                    except UnicodeDecodeError:skipped+=1;continue
                if excluded(path,text):skipped+=1;continue
                # Preserve text/line identity; do not normalize newlines or Unicode.
                if text.strip():files[path]=text
    except (BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise WorkspaceConflict('invalid_project_archive') from exc
    if not files:raise WorkspaceConflict('no_indexable_project_files')
    # GitHub/codeload zips have one enclosing directory, which is not a repo path.
    roots={PurePosixPath(p).parts[0] for p in files}
    removed_root=None
    if strip_single_root and len(roots)==1 and all(len(PurePosixPath(p).parts)>1 for p in files):
        removed_root=next(iter(roots))
        files={'/'.join(PurePosixPath(p).parts[1:]):text for p,text in files.items()}
    return files,{'archive_sha256':sha256(data).hexdigest(),'skipped_files':skipped,'stored_files':len(files),
                  'executed':False,'safety_version':'zip-scan-v3-2','file_hash_basis':'sha256_of_decoded_text_utf8; newlines_preserved',
                  'decoding':'utf8-sig_or_gb18030; unrecognized_and_binary_excluded','removed_root':removed_root}
