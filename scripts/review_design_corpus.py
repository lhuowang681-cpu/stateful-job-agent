"""One bounded design-coverage supplement: 10 new questions, no retuning."""
import json,sys,subprocess
from pathlib import Path
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from job_agent.knowledge.evaluation_contract import EvaluationDataset
from job_agent.knowledge.index_manifest import fingerprint


def main():
    path=ROOT/'docs/evaluation/expansion/review-real-design-addendum-v1.json'
    if path.exists():raise ValueError('refuse_overwrite_design_addendum')
    primary=json.loads((ROOT/'docs/evaluation/expansion/review-real-project-chinese-v3.json').read_text(encoding='utf-8'))
    control=next(c for c in primary['cases'] if c['case_id']=='real-dev-code_rag-1')
    docs=[next(d for d in primary['corpus']['documents'] if d['document_id']==control['gold'][0]['document_id'])]
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    filenames={'S2':'S2-retrieval.md','S4':'S4-collaboration.md','S5':'S5-postgres-slice.md','S6':'S6-outbox-streams.md','S7':'S7-learning-loop.md'}
    for key,name in filenames.items():
        relative='docs/tech-specs/expansion/'+name;text=(ROOT/relative).read_text(encoding='utf-8')
        docs.append({'document_id':'test-code/'+relative,'kind':'project_documentation','split':'test','text':text,
            'content_hash':sha256(text.encode()).hexdigest(),'origin':relative,'source_version':revision,
            'license':'Project owner authorized internal evaluation; no redistribution license asserted'})
    def span(key,anchor,section=False):
        doc=next(d for d in docs if d['origin'].endswith(filenames[key]));lines=doc['text'].splitlines(keepends=True)
        start=next(i for i,line in enumerate(lines) if anchor in line);end=start+1
        if section:
            while end<len(lines) and not lines[end].startswith('## '):end+=1
        else:
            while end<len(lines) and lines[end].strip():end+=1
        while end>start+1 and not lines[end-1].strip():end-=1
        return {'document_id':doc['document_id'],'content_hash':doc['content_hash'],'start_line':start+1,
            'end_line':end,'quote':''.join(lines[start:end])}
    questions=[
        ('S2','为什么S2保留默认BM25并显式启用本地向量，而没有直接引入新向量数据库？',[span('S2','## 问题、目标与取舍',True)]),
        ('S2','S2的模型可选配置与S4的改写硬门禁分别保护什么边界，为什么模型同意不能代替原文依据？',[span('S2','## 数据及接口合同',True),span('S4','3. 新claim_audit.py')]),
        ('S4','共享执行状态为什么沿用已有仓储而不开第二权威库，角色摘要为什么排除owner与租约？',[span('S4','1. 新execution_state.py')]),
        ('S4','Writer或面试的未知派发，能否按可重建索引任务那样自动重放？S4与S6如何划分？',[span('S4','2. 两图State'),span('S6','## 范围与复用',True)]),
        ('S5','S5为什么只抽取项目、索引和任务的持久化接口，没有把所有旧Run模型与数据域一起迁移？',[span('S5','## 事务域与接口',True)]),
        ('S5','PG项目来源与SQLite学习观察之间能否声称有分布式事务，跨域引用如何保持有效性？',[span('S5','原API路径/DTO'),span('S7','学习域与面试同一SQLite事务域')]),
        ('S6','Redis消息为什么只带定位字段而不授权owner，模式切换为什么需要持久authority epoch？',[span('S6','## 权威状态与schema迁移',True)]),
        ('S6','Stream裁掉pending后为何仍要依靠PG对账恢复，为什么ACK不能证明零丢失，权威发布又在哪里提交？',[span('S6','XAUTOCLAIM仅转消费所有权'),span('S5','2. task完成')]),
        ('S7','用户确认、纠正与多场一致观察，为什么都不能直接写成个人掌握或现实贡献？',[span('S7','原评价与用户自述分开')]),
        ('S7','再次练习为什么复用固定题目却不复用旧回答，比较为什么还要绑定模型和方法条件？',[span('S7','## 复习与再次练习',True),span('S4','1. 新execution_state.py')]),
    ]
    snapshot='corpus-'+fingerprint(sorted(docs,key=lambda d:d['document_id']))
    control['source_snapshot']=snapshot;control['annotation_note']='Previously observed dev control only; not a new quality sample or tuning opportunity.'
    cases=[control]
    for i,(family,query,gold) in enumerate(questions):
        cases.append({'case_id':f'design-addendum-{family}-{i+1}','family':'design-'+family,'source_snapshot':snapshot,
            'query':query,'category':'multi_evidence' if len(gold)>1 else 'documentation','answerable':True,'gold':gold,
            'gold_requirement':'all','split':'test','annotation_status':'ai_candidate','retrieval_scope':'project',
            'annotation_note':'New AI candidate about the dated design contract, not proof of current runtime results; human verification deferred.',
            'unanswerable_reason':None})
    data={'dataset_version':'review-real-design-addendum-1','corpus':{'snapshot_id':snapshot,'documents':docs},'cases':cases,
        'policy':'10 new design candidates plus one previously seen dev control; total unique review questions 50 with primary40. No retuning; preserve original v3 E selection. Dated Specs describe design intent, not new executed results.'}
    EvaluationDataset.model_validate(data)
    assert len(cases)==11 and sum(c['split']=='test' for c in cases)==10
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    freeze=json.loads((ROOT/'docs/evaluation/expansion/review-real-project-freeze-v3.json').read_text(encoding='utf-8'))
    record={'version':'design-addendum-freeze-1','new_questions':10,'total_unique_review_questions':50,
        'dataset_sha256':sha256(path.read_bytes()).hexdigest(),'source_revision':revision,'corpus_characters':sum(len(d['text']) for d in docs),
        'selected_research_profile':freeze['selected_research_profile'],'runtime':freeze['runtime'],'test_variants':freeze['test_variants'],
        'repeats':3,'limit':5,'tuning_rounds':0,'human_reviewed':0,'prior_primary_test_already_seen':True,'metrics_must_be_reported_separately':True}
    path.with_suffix('.freeze.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in record.items() if k not in ('runtime','test_variants')}))


if __name__=='__main__':main()
