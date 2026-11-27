"""Prepare a small source-based HUMAN review packet; no automatic approval."""
from difflib import SequenceMatcher
from hashlib import sha256
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from job_agent.knowledge.evaluation_contract import EvaluationDataset


def main():
    path=ROOT/'docs/evaluation/expansion/candidates-v3.json';raw=path.read_bytes();data=EvaluationDataset.model_validate_json(raw)
    selected={'dev-final-06','dev-final-11','dev-final-16','dev-final-22','test-final-08','test-final-09','test-final-15','test-final-22'}
    cases=[c for c in data.cases if c.case_id in selected]
    packet={'dataset_version':data.dataset_version,'dataset_sha256':sha256(raw).hexdigest(),
        'status':'awaiting_human_review','human_reviewed_count':0,'cases':[c.model_dump() for c in cases]}
    output=ROOT/'docs/evaluation/expansion';(output/'human-review-packet-v1.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 8题人工核对包（当前尚未有人审核）','',f'固定数据：{data.dataset_version}；SHA256 `{packet["dataset_sha256"]}`。',
        '','预计15—20分钟。请逐题判断：原文能否支持这个问题的候选定位？范围是否过宽？多证据是否都必要，any是否确有替代关系？无答案理由是否成立？',
        '','可回复：`编号：支持 / 需缩小范围 / 不支持 / 不确定；说明`。只有明确收到的人工逐题意见才计为人工审核；“稍后”不会改变状态。下列定位仍是AI候选，不是预先给定的真值。',
        '','开发/测试各4题。这里只核对固定合成原文，不验证个人能力或真实贡献。']
    for case in cases:
        lines += ['',f'## {case.case_id} · {case.category}',case.query,'',f'证据需求：{case.gold_requirement}；检索域：{case.retrieval_scope}。']
        if not case.answerable:lines+=['',f'候选无答案理由：{case.unanswerable_reason}']
        for gold in case.gold:
            lines+=['',f'来源 `{gold.document_id}`，第{gold.start_line}—{gold.end_line}行：','```',gold.quote.rstrip('\n'),'```']
    lines+=['','## 划分与近重复提醒','源文件/问题family机械隔离不等于语义完全独立；请同时指出问题是否只是另一题改名或同义改写。',
        'v2候选曾把“本地事务能否涵盖任意外部操作”与测试侧的跨系统事务问题重复，AI审阅已发现；保留v2，v3把开发题改为“消费组pending与业务完成的区分”，未看测试分数后调策略。其余语义近重复仍待人工。','']
    (output/'HUMAN_REVIEW_8.md').write_text('\n'.join(lines),encoding='utf-8')
    pairs=[]
    for a in data.cases:
        if a.split!='dev':continue
        for b in data.cases:
            if b.split!='test':continue
            score=SequenceMatcher(None,a.query.casefold(),b.query.casefold(),autojunk=False).ratio()
            pairs.append({'left':a.case_id,'right':b.case_id,'text_similarity':round(score,4),'left_query':a.query,'right_query':b.query})
    pairs.sort(key=lambda r:(-r['text_similarity'],r['left'],r['right']))
    report={'dataset_sha256':packet['dataset_sha256'],'status':'mechanical_only_human_semantic_review_pending',
        'cross_split_pairs':len(pairs),'top_text_pairs':pairs[:12],
        'known_pre_score_revision':{'rejected_version':'candidates-v2.json','dev_case':'dev-final-28','test_case':'test-final-36',
            'reason':'cross-system transaction question shared the same semantic fact; v3 dev question changed before any scoring'},
        'threshold_used_for_quality_gate':None,'semantic_duplicate_clearance':None}
    (output/'near-duplicate-audit-v1.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'cases_prepared':len(cases),'human_reviewed':0,'cross_split_text_pairs':len(pairs)}))


if __name__=='__main__':main()
