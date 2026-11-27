"""One finite new-source16-question holdout, frozen before development scoring."""
import ast,json,subprocess,sys
from hashlib import sha256
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from job_agent.knowledge.evaluation_contract import CorpusDocument,CorpusSnapshot,EvaluationDataset,EvalCase,GoldSpan
from job_agent.knowledge.index_manifest import fingerprint
from job_agent.knowledge.support_evaluation import SupportLabel


def freeze():
    folder=ROOT/'docs/evaluation/expansion';path=folder/'rag-round3-new16-v1.json';assert not path.exists()
    source_version=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    old=EvaluationDataset.model_validate_json((folder/'review-real-project-chinese-v3.json').read_text(encoding='utf-8'))
    documents=[d for d in old.corpus.documents if d.split=='dev']
    origins=['ingestion.py','project_import.py','github_import.py','pdf_export.py','match_repository.py','matching.py','parsing.py']
    origins=['src/job_agent/resume_workspace/'+p for p in origins]+['docs/tech-specs/expansion/S1-corpus-contract.md','docs/tech-specs/expansion/S3-evidence-pack.md']
    fresh={}
    for origin in origins:
        text=subprocess.check_output(['git','show',source_version+':'+origin],cwd=ROOT).decode('utf-8')
        doc=CorpusDocument(document_id='test-code/'+origin,kind='code' if origin.endswith('.py') else 'project_documentation',
            split='test',text=text,content_hash=sha256(text.encode()).hexdigest(),origin=origin,source_version=source_version,
            license='Project owner authorized internal evaluation; no redistribution license asserted')
        documents.append(doc);fresh[Path(origin).name]=doc
    snapshot=CorpusSnapshot(snapshot_id='corpus-'+fingerprint([d.model_dump() for d in sorted(documents,key=lambda d:d.document_id)]),documents=documents)
    cases=[c.model_copy(update={'source_snapshot':snapshot.snapshot_id}) for c in old.cases if c.split=='dev'];labels=[]
    def span(name,start,end):
        doc=fresh[name];return GoldSpan(document_id=doc.document_id,content_hash=doc.content_hash,start_line=start,end_line=end,
                                       quote=''.join(doc.text.splitlines(keepends=True)[start-1:end]))
    def function(name,qualified):
        tree=ast.parse(fresh[name].text)
        if '.' in qualified:
            cls,method=qualified.split('.',1);parent=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==cls)
            n=next(n for n in parent.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==method)
        else:n=next(n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==qualified)
        return span(name,n.lineno,n.end_lineno)
    def paragraph(name,needle):
        lines=fresh[name].text.splitlines();start=next(i for i,t in enumerate(lines,1) if needle in t)
        end=start
        while end<len(lines) and lines[end].strip():end+=1
        return span(name,start,end)
    def add(key,family,query,category,whole,minimum,reason):
        case=EvalCase(case_id='rag16-'+key,family='new-source-'+family,source_snapshot=snapshot.snapshot_id,query=query,
            category=category,answerable=bool(whole),gold=whole,split='test',annotation_note=reason,
            unanswerable_reason=None if whole else reason,retrieval_scope='project')
        cases.append(case);labels.append(SupportLabel(case_id=case.case_id,corpus_snapshot=snapshot.snapshot_id,answerable=case.answerable,
            minimal_spans=minimum,symbol_ranges=[s for s in whole if s.document_id.endswith('.py')],rationale=reason).model_dump())
    add('upload-limits','upload','上传文件如何拒绝不支持格式、空内容、超大字节，以及加密或页数过多的PDF？','natural_language',
        [function('ingestion.py','extract_upload')],[span('ingestion.py',17,35)],'Need all early upload/PDF checks; not OCR or successful document extraction.')
    add('archive-path','archive','checked_path 如何拒绝父目录、反斜杠、过深目录以及Windows保留设备名？','exact_symbol',
        [function('project_import.py','checked_path')],[span('project_import.py',23,31)],'Canonical Unicode, unsafe components, depth and platform device names together.')
    add('zip-preflight','archive','项目ZIP在读取内容前如何处理展开规模、加密项、符号链接、重复路径和压缩炸弹？','natural_language',
        [function('project_import.py','scan_zip')],[span('project_import.py',44,64)],'Requires all pre-decompression checks, not a claim that importing executes tests.')
    add('github-boundary','github','GitHub导入怎样限制仓库URL格式，并防止下载域名解析到内网地址？','multi_evidence',
        [function('github_import.py','repository_slug'),function('github_import.py','check_public_host')],
        [span('github_import.py',24,31),span('github_import.py',35,39)],'Separate URL and DNS checks; static safeguards do not prove a real account scan.')
    add('pdf-owner-hash','pdf','下载已生成PDF时，怎样同时检查所属用户、确认过的版本以及PDF字节完整性？','natural_language',
        [function('pdf_export.py','PDFRepository._get')],[span('pdf_export.py',140,150)],'Owner join, source version confirmation and hash must all be checked.')
    add('match-load','matching-read','读取岗位匹配结果时怎样重新校验载荷hash和简历版本，而不是直接信任缓存JSON？','natural_language',
        [function('match_repository.py','MatchRepository._load')],[span('match_repository.py',106,114)],'Need incomplete status guard, payload hash, current source validation and delegated binding check.')
    add('source-read','source-store','VersionSourceStore.read 在什么情况下拒绝返回文本，目录hash如何与实际文本重新核对？','exact_symbol',
        [function('matching.py','VersionSourceStore.read')],[span('matching.py',74,78)],'Catalog document lookup plus exact text digest; no personal fact verification implied.')
    add('parse-exact','parse','materialize 怎样拒绝重复字段、找不到或不唯一的原文，以及稀疏数组下标？','exact_symbol',
        [function('parsing.py','materialize')],[span('parsing.py',37,54),span('parsing.py',58,66)],'All unique quote/path and sparse-index controls are necessary; model defaults are not evidence.')
    add('match-chain','match-provenance','MatchRepository._validate_payload 经 row_views 到 validate_bundle 时，怎样避免JD自身冒充C1简历证据？','multi_evidence',
        [function('match_repository.py','MatchRepository._validate_payload'),function('matching.py','row_views'),function('matching.py','validate_bundle')],
        [span('match_repository.py',90,103),span('matching.py',271,275),span('matching.py',245,268)],'Read/write binding, real delegated validation and C1 source scope are distinct requirements.')
    add('upload-versus-quote','input-chain','extract_upload 与 materialize 两处怎样分别约束上传字节和字段引用的原文唯一性？','multi_evidence',
        [function('ingestion.py','extract_upload'),function('parsing.py','materialize')],
        [span('ingestion.py',17,23),span('parsing.py',37,54)],'Compare two actual validation responsibilities without inventing a direct call edge.')
    add('identity-design','identity-spec','S1设计为什么把模型版本、维度、query模板、输入顺序与可信scope都放进索引身份？','documentation',
        [paragraph('S1-corpus-contract.md','`knowledge/index_manifest.py`'),paragraph('S1-corpus-contract.md','CodeRAG复用现有vectors')],
        [paragraph('S1-corpus-contract.md','`knowledge/index_manifest.py`'),paragraph('S1-corpus-contract.md','CodeRAG复用现有vectors')],
        'Dated design intention only; not evidence of deployment or human review completion.')
    add('pack-design','pack-spec','S3中原文定位、断言支持与个人运行成果为什么分开，预算用尽后应保留什么不足信息？','documentation',
        [paragraph('S3-evidence-pack.md','- ClaimAssessment独立'),paragraph('S3-evidence-pack.md','3. 所有调用前检查')],
        [paragraph('S3-evidence-pack.md','- ClaimAssessment独立'),paragraph('S3-evidence-pack.md','3. 所有调用前检查')],
        'Dated design contract, not actual measurement. Source support and bounded execution are separate.')
    for key,family,query,reason in [
      ('ocr-measurement','upload','扫描PDF的OCR识别率已经达到99.9%，这次真实测量的样本在哪里？','No OCR accuracy measurement or sample is provided; code says needs_ocr, not99.9% success.'),
      ('all-private-scanned','github','这个导入器已经扫描用户账号的全部私有仓库并完成生产部署，具体记录是什么？','No real account-wide private scan or deployment evidence; importer safeguards cannot establish this premise.'),
      ('historical-human','identity-spec','旧S1里的计划是否已经完成本周全部人工核对，实际通过率是多少？','Dated in_progress design/plan cannot establish current human review completion or rate.'),
      ('pdf-outcome','pdf','两个PDF模板中哪一个真实录用率更高，线上对照数据是多少？','Template rendering code has no hiring outcome controlled trial or online business measurements.')]:
        add(key,family,query,'unanswerable',[],[],reason)
    result=EvaluationDataset(dataset_version='rag-round3-new16-1',corpus=snapshot,cases=cases,
        policy='Old20 dev observed;16 new test source paths disjoint. AI labels/human0. Same-project concepts may overlap; not cross-project generalization. One formal test reservation after development lock.')
    assert len([c for c in cases if c.split=='test'])==16 and sum(c.answerable for c in cases if c.split=='test')==12
    old_origins={d.origin for d in old.corpus.documents}
    assert not old_origins.intersection(origins)
    for name,value in [(path,result.model_dump()),(folder/'rag-round3-new16-support-v1.json',{'version':'support-label-file-1','source_git':source_version,
                        'corpus_snapshot':snapshot.snapshot_id,'labels':labels,'human_reviewed':0})]:
        with name.open('x',encoding='utf-8',newline='\n') as stream:json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')
    report={'status':'frozen_before_dev_scoring','test_cases':16,'answerable_test':12,'test_source_paths':origins,
            'test_sources_disjoint_from_all_old40':True,'source_git':source_version,'human_reviewed':0,
            'dataset_sha256':sha256(path.read_bytes()).hexdigest(),'support_labels_sha256':sha256((folder/'rag-round3-new16-support-v1.json').read_bytes()).hexdigest()}
    with (folder/'rag-round3-new16-freeze-v1.json').open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=False,indent=2)
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':freeze()
