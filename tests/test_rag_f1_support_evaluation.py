"""Real scoring risks: holes, identity mixing, rank and context budget inflation."""
from hashlib import sha256
import pytest
from job_agent.knowledge.evaluation_contract import CorpusDocument,CorpusSnapshot,EvalCase,GoldSpan,evaluate_case
from job_agent.knowledge.index_manifest import fingerprint
from job_agent.knowledge.support_evaluation import SupportLabel,LocatedSpan,evaluate_support


@pytest.fixture
def sample():
    docs=[CorpusDocument(document_id=name,kind='code',split='dev',text=''.join(f'{name} line {i}\n' for i in range(1,25)),
             content_hash=sha256(''.join(f'{name} line {i}\n' for i in range(1,25)).encode()).hexdigest(),origin=name,source_version='commit-1',license='test') for name in ('a.py','b.py')]
    corpus=CorpusSnapshot(snapshot_id='corpus-'+fingerprint([d.model_dump() for d in docs]),documents=docs)
    def span(start,end,name='a.py'):
        doc=next(d for d in docs if d.document_id==name)
        return GoldSpan(document_id=name,content_hash=doc.content_hash,start_line=start,end_line=end,quote=''.join(doc.text.splitlines(keepends=True)[start-1:end]))
    case=EvalCase(case_id='case',family='family',source_snapshot=corpus.snapshot_id,query='explain',category='natural_language',answerable=True,
                  gold=[span(1,20)],split='dev',annotation_note='Original whole function remains fixed')
    label=SupportLabel(case_id='case',corpus_snapshot=corpus.snapshot_id,answerable=True,minimal_spans=[span(3,8)],symbol_ranges=[span(1,20)],rationale='Conditions and return together support the question')
    def hit(start,end,name='a.py',**kw):
        return LocatedSpan(span=span(start,end,name),corpus_snapshot=corpus.snapshot_id,source_version='commit-1',snapshot_id='scope-1').model_copy(update=kw)
    def score(hits,**kw):return evaluate_support(case,corpus,label,hits,snapshot_id='scope-1',**kw)
    return corpus,case,label,span,hit,score


@pytest.mark.parametrize('ranges,complete,coverage',[
    ([(3,5),(6,8)],True,1.), ([(3,6),(5,8)],True,1.), ([(3,4),(6,8)],False,5/6),
    ([(3,5),(3,5)],False,.5), ([],False,0.)])
def test_union_preserves_holes_and_deduplicates_overlap(sample,ranges,complete,coverage):
    _,_,_,_,hit,score=sample;r=score([hit(a,b) for a,b in ranges])
    assert r['minimal_union_sufficient'] is complete
    assert r['minimal_line_coverage']==coverage
    assert r['minimal_single_sufficient'] is False


@pytest.mark.parametrize('wrong',[
    {'source_version':'commit-2'},{'snapshot_id':'scope-2'},{'corpus_snapshot':'corpus-other'}])
def test_matching_quote_cannot_complete_union_from_wrong_identity(sample,wrong):
    _,_,_,_,hit,score=sample;r=score([hit(3,5),hit(6,8,**wrong)])
    assert not r['minimal_union_sufficient'] and r['minimal_line_coverage']==.5
    assert len(r['rejected_citations'])==1


def test_other_file_invalid_hash_and_quote_do_not_complete_union(sample):
    _,_,_,span,hit,score=sample
    other=hit(6,8,'b.py');bad=hit(6,8,span=span(6,8).model_copy(update={'quote':'fabricated'}))
    bad_hash=hit(6,8,span=span(6,8).model_copy(update={'content_hash':'0'*64}))
    r=score([hit(3,5),other,bad,bad_hash])
    assert r['minimal_line_coverage']==.5 and len(r['rejected_citations'])==2


def test_rank_budget_counts_invalid_citations(sample):
    _,_,_,_,hit,score=sample
    r=score([hit(3,8,snapshot_id='other')]*5+[hit(3,8)])
    assert not r['minimal_union_sufficient'] and r['validated_bounded_citations']==0


def test_redundant_large_context_cannot_buy_unbounded_score(sample):
    _,_,_,_,hit,score=sample
    r=score([hit(1,24)],max_span_lines=10)
    assert not r['minimal_union_sufficient'] and r['rejected_citations'][0]['reason']=='context_budget_exceeded'
    r=score([hit(3,5),hit(6,8)],context_char_budget=len(hit(3,5).span.quote))
    assert not r['minimal_union_sufficient'] and r['minimal_line_coverage']==.5


def test_multiple_evidence_all_vs_any_and_file_symbol_location_are_distinct(sample):
    corpus,case,label,span,hit,_=sample
    label=label.model_copy(update={'minimal_spans':[span(3,8),span(4,7,'b.py')],'symbol_ranges':[span(1,20),span(1,20,'b.py')]})
    r=evaluate_support(case,corpus,label,[hit(3,8)],snapshot_id='scope-1')
    assert r['file_location_recall']==.5 and r['symbol_range_location_recall']==.5 and not r['minimal_union_sufficient']
    assert evaluate_support(case,corpus,label.model_copy(update={'requirement':'any'}),[hit(3,8)],snapshot_id='scope-1')['minimal_union_sufficient']


def test_old_strict_metric_unchanged_while_new_label_is_separate(sample):
    corpus,case,_,_,hit,score=sample;r=score([hit(3,8)])
    assert r['minimal_union_sufficient'] and not r['legacy_strict_single_citation']['hit_any_gold']
    assert r['legacy_strict_single_citation']==evaluate_case(case,corpus,[hit(3,8).span])


def test_original_whole_gold_can_be_covered_by_two_valid_chunks(sample):
    _,_,_,_,hit,score=sample;r=score([hit(1,10),hit(11,20)])
    assert not r['legacy_strict_single_citation']['sufficient_gold_retrieved']
    assert r['original_gold_union_sufficient'] and r['original_gold_union_line_coverage']==1.


def test_unanswerable_context_is_not_correct_refusal(sample):
    corpus,case,label,_,hit,_=sample
    case=case.model_copy(update={'answerable':False,'gold':[],'unanswerable_reason':'No runtime record'})
    label=label.model_copy(update={'answerable':False,'minimal_spans':[],'symbol_ranges':[]})
    r=evaluate_support(case,corpus,label,[hit(3,8)],snapshot_id='scope-1')
    assert r['minimal_union_sufficient'] is None and r['unanswerable_has_context']
    assert r['correct_refusal'] is None and r['generated_claim_support'] is None
