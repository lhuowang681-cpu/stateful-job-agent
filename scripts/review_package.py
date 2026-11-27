"""Package the reviewed Git file set and audited owner-source research bundles.

Never includes an untracked file by walking the workspace. Concurrent teaching
changes to AGENTS.md are preserved locally; the archive uses its committed bytes.
"""
import argparse
import io
import json
import re
import subprocess
import sys
import zipfile
from hashlib import sha256
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]


def digest(value):
    return sha256(value).hexdigest()


def write_new(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def checked_name(name):
    path = PurePosixPath(name)
    if not name or '\\' in name or path.is_absolute() or '..' in path.parts or ':' in name:
        raise ValueError('unsafe_package_path')
    return path


def source_files():
    snapshot = zipfile.ZipFile(io.BytesIO(subprocess.check_output(['git', 'archive', '--format=zip', 'HEAD'], cwd=ROOT)))
    names = [name for name in snapshot.namelist() if not name.endswith('/')]
    files = {}
    for name in filter(None, names):
        checked_name(name)
        if (any(part in ('.git', 'node_modules', '__pycache__', 'handbook', 'textbook') or part.endswith('.egg-info') for part in PurePosixPath(name).parts)
                or name.endswith(('.pyc', '.log', 'COACHING_PROGRESS.json')) or Path(name).name == '.env'):
            continue
        if name.endswith(('.sqlite', '.db')):
            raise ValueError('database_in_source_file_set:' + name)
        value = snapshot.read(name)
        if re.search(rb'\bsk-[A-Za-z0-9_-]{30,}\b', value):
            raise ValueError('possible_secret_in_package:' + name)
        files[name] = value
    if not any(name.endswith('.mjs') and 'pdf.worker' in name for name in files):
        raise ValueError('pdf_worker_not_tracked')
    return files


def package(output, name, files, context):
    manifest = dict(schema_version='review-package-1', name=name,
                    files={key: digest(value) for key, value in sorted(files.items())}, **context)
    archive = output / (name + '.zip')
    with zipfile.ZipFile(archive, 'x', zipfile.ZIP_DEFLATED) as stream:
        for key, value in sorted(files.items()):
            checked_name(key)
            stream.writestr(key, value)
        stream.writestr('REVIEW_PACKAGE_MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    extracted = output / ('unpacked-' + name)
    extracted.mkdir(exist_ok=False)
    with zipfile.ZipFile(archive) as stream:
        assert stream.testzip() is None
        names = stream.namelist()
        assert len(names) == len(set(names))
        for entry in stream.infolist():
            checked_name(entry.filename)
            assert (entry.external_attr >> 16) & 0o170000 != 0o120000
            data = stream.read(entry)
            if entry.filename != 'REVIEW_PACKAGE_MANIFEST.json':
                assert digest(data) == manifest['files'][entry.filename]
            destination = extracted / entry.filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
    assert all(digest((extracted / key).read_bytes()) == value for key, value in manifest['files'].items())
    value = dict(file=archive.name, sha256=digest(archive.read_bytes()), files=len(files), bytes=archive.stat().st_size,
                 crc_and_all_extracted_hashes='passed', unpacked_directory=extracted.name)
    (output / (name + '.sha256')).write_text(value['sha256'] + '  ' + archive.name + '\n', encoding='utf-8')
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / 'output' / 'review-20261023'):
        raise ValueError('output_outside_review_directory')
    output.mkdir(parents=True, exist_ok=False)
    sources = source_files()
    learning = {key: value for key, value in sources.items() if
                key in ('FEATURE_MATRIX.md', 'docs/CONTINUE_DEVELOPMENT.md') or
                (key.startswith(('docs/tech-specs/', 'docs/devlog/REVIEW-', 'docs/demo/REVIEW_',
                                 'docs/learning/REVIEW_')) and not key.endswith('.jsonl'))}
    from job_agent.knowledge.research_contract import inspect_bundle
    research = {}
    for name in ('r4-real-index-v3', 'r4-design-index-v1'):
        directory = ROOT / 'output' / 'review-20261023' / name
        inspect_bundle(ROOT, directory, strict_algorithm=True)
        expected = {'manifest.json', 'dataset.json', 'dev.sqlite', 'test.sqlite',
                    'dev-public-vectors.json', 'test-public-vectors.json', 'heldout-reservation.json'}
        assert {path.name for path in directory.iterdir()} == expected
        for path in directory.iterdir():
            research['research/' + name + '/' + path.name] = path.read_bytes()
    for key, value in sources.items():
        if ((key.startswith('docs/devlog/evidence/review-20261023/r4-') or
             key.startswith('docs/evaluation/expansion/review-real-')) or
                key in ('docs/devlog/REVIEW-R4.md', 'docs/demo/REVIEW_RUNBOOK.md')):
            research[key] = value
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    common = dict(git_revision=revision, private_material_included=False, model_weights_included=False,
                  runtimes_included=False, git_history_included=False, human_reviewed_count=0,
                  source_file_policy='reviewed committed Git snapshot; concurrent working-tree teaching changes excluded')
    results = [package(output, 'job-agent-review-source', sources, common),
               package(output, 'job-agent-review-learning', learning, common),
               package(output, 'job-agent-review-real-research', research,
                       dict(common, source_kind='owner_project_source', synthetic_only=False,
                            permission='Owner authorized internal evaluation; no redistribution license asserted',
                            databases='Only inspected fixed research indices; no populated user workspace tables'))]
    report = dict(schema_version='review-delivery-1', packages=results, source_git_revision=revision,
                  status='hash_and_unpack_passed_runtime_checks_are_separate',
                  runtime_verification='verification.json beside these archives; never infer HTTP from ZIP success')
    write_new(output / 'delivery.json', report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
