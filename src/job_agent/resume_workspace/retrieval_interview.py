"""Retrieval extension of the existing checkpointed, bounded interview graph."""
from job_agent.resume_workspace.interview_collaboration import InterviewEngine
from job_agent.resume_workspace.interview_contracts import Topic
from job_agent.resume_workspace.interview_tools import InterviewTools
from job_agent.resume_workspace.evidence_reference import EvidenceReference
from job_agent.resume_workspace.repository import WorkspaceConflict
from job_agent.resume_workspace.project_evidence import make_question_boundary


class RetrievalInterviewEngine(InterviewEngine):
    def __init__(self,workspace,knowledge,code,provider=None):
        super().__init__(provider);self.workspace=workspace;self.knowledge=knowledge;self.code=code

    def _tools(self,s):
        if not s.bound_owner:raise WorkspaceConflict('interview_tool_scope_missing')
        return InterviewTools(self.workspace,self.knowledge,self.code,s.bound_owner,s.project_id,s.snapshot_id)

    def prepare(self,owner,state,request,store,*,learning_context=None):
        if not request.use_retrieval:return
        state.bound_owner=owner;state.use_retrieval=True;state.track=request.track
        state.project_id=request.project_id;state.snapshot_id=request.snapshot_id;state.prior_session_id=request.prior_session_id
        if state.mode=='local_demo':state.model='scoped-retrieval-rules-v3'
        if learning_context:
            state.plan=[learning_context[0]]
            state.messages.append({'from':'coordinator','to':'interviewer','type':'learning_fixed_source','turn':0,
                'detail':'复用已核对观察的固定题目与来源；新场次不包含旧回答，仍不认定掌握。'})
            return
        tools=self._tools(state);query=request.jd_text[:600]
        if request.track=='weakness':
            previous=store.review(owner,request.prior_session_id)
            weak=[t for t in previous['turns'] if t['missing'] and not t.get('assessment_withdrawn')]
            if not weak:raise WorkspaceConflict('interview_no_recorded_weakness')
            query=('AST 静态 源码 符号 引用 commit' if previous['track']=='project' else
                ' '.join(t['question']+' '+' '.join(t['missing']) for t in weak)[:600])
        if request.track=='project':
            pack=tools.retrieve_pack(state,'interviewer',query,scope_kind='private_project')
            found={'hits':[i.model_dump(mode='json') for i in pack.items]}
            topics=[];seen=set()
            for hit in found['hits']:
                symbol=hit['symbol']
                if not symbol or symbol['symbol_id'] in seen:continue
                seen.add(symbol['symbol_id']);ref=EvidenceReference.model_validate(hit['reference'])
                name=symbol['qualified_name']
                references=[ref]
                if pack.plan.kind=='cross_file':
                    paths={ref.path}
                    for item in pack.items:
                        if item.reference.path not in paths:
                            references.append(item.reference);paths.add(item.reference.path)
                        if len(references)>=3:break
                boundary=make_question_boundary(pack,references,symbol)
                topics.append(Topic(anchor_id='code:'+symbol['symbol_id'],
                    prompt=f'{boundary.scope_note} 请结合 {ref.path} 中 {name} 的所引行段，说明可见行为和输入或返回边界；未展示的部分请明确无法判断。',
                    points={'p0':'准确解释引用片段中可见的实现，未展示部分不推测','p1':'说明一项可见输入/返回/失败边界；未显示则明确无法判断','p2':'区分固定快照静态源码、历史设计与当前运行成果/个人贡献，不把原主题前提当事实'},
                    aliases={'p0':[symbol['name'],ref.path],'p1':['输入','返回','异常','失败','边界','error','超时','未显示'],
                        'p2':['未运行','静态','贡献','参与范围','不能证明']},
                    followups={'p0':'请回到引用函数，具体指出你描述的行为对应哪些语句。',
                        'p1':'引用中可见什么输入检查或返回条件？未展示的失败分支请不要推测。',
                        'p2':'这些固定引用能证明什么，哪些当前状态、运行成果或个人贡献仍需其他材料？'},references=references,evidence_boundary=boundary))
            if not topics:raise WorkspaceConflict('interview_no_project_symbols_found')
            state.plan=topics[:3]
        else:
            pack=tools.retrieve_pack(state,'interviewer',query,scope_kind='public_questions')
            found={'hits':[i.model_dump(mode='json') for i in pack.items]}
            topics=[]
            for hit in found['hits']:
                entry,_=self.knowledge.private_question(hit['entry']['entry_id'])
                keys=[f'p{i}' for i in range(len(entry.answer_points))]
                topics.append(Topic(anchor_id=entry.entry_id,prompt=entry.body,
                    points=dict(zip(keys,entry.answer_points)),aliases=dict(zip(keys,entry.aliases)),
                    followups=dict(zip(keys,entry.followups)),references=[EvidenceReference.model_validate(hit['reference'])]))
            if not topics:raise WorkspaceConflict('interview_no_public_questions_found')
            state.plan=topics[:3]
        state.messages.append({'from':'coordinator','to':'interviewer','type':'scoped_plan','turn':0,
            'detail':'已根据所选范围实际检索，固定本场来源；参考资料不能证明个人经历。'})

    def _invoke(self,role,s,payload,schema,save):
        if not s.use_retrieval:return super()._invoke(role,s,payload,schema,save)
        topic=s.plan[s.topic_index]
        payload={**payload,'shared_evidence_packs':[p.role_summary() for p in s.evidence_packs[-2:]]}
        if role=='evaluator':
            import re
            answer=payload['answer']
            # Exact answer substrings aid copying; no judgement or partition is supplied.
            quote_candidates=[part[:80] for part in re.findall(r'[^。！？；;\n]+[。！？；;]?',answer) if part.strip()][:20]
            payload={**payload,'reference_data':[r.model_dump(mode='json',exclude={'owner_id','project_id','source_id','evidence_id'}) for r in s.current.references],
                'evaluation_output_contract':{'required_point_ids':list(topic.points),
                    'answer_quote_origin':'Only exact contiguous substrings of answer; never rubric, reference_data or pack claims.',
                    'answer_quote_candidates':quote_candidates,
                    'partition':'Every required ID exactly once in covered_ids OR missing_ids; correct only covered, incorrect/uncertain only missing.'},
                'project_evidence_boundary':s.current.evidence_boundary.model_dump() if s.current.evidence_boundary else None,
                'evaluation_boundary':'Evaluate only the actual bounded practice question, not the original unsupported topic. Source shows static implementation, not runtime success/current deployment or personal contribution. A partial quote cannot establish omitted behavior. Local rules are lexical only.'}
        elif role=='interviewer':
            payload={**payload,'permitted_retrieval_targets':['none','symbol','references','tests'] if s.project_id else ['none','public_docs'],
                'reference_locations':[{'path':r.path,'start':r.start_line,'end':r.end_line} for r in s.current.references]}
        decision=super()._invoke(role,s,payload,schema,save)
        if role!='interviewer':return decision
        if decision.action!='follow_up' or s.current.followup or s.revision+1>=s.max_turns:
            decision.retrieval_target='none';return decision
        if s.mode=='local_demo':
            decision.retrieval_target=('tests' if any(x in s.pending.answer.casefold() for x in ['测试','test']) else 'references') if s.project_id else 'public_docs'
        target=decision.retrieval_target
        tools=self._tools(s)
        if s.project_id and target in ('symbol','references','tests'):
            name=topic.anchor_id.removeprefix('code:')
            actions=[('get_symbol',{'name':name})]
            if target in ('references','tests'):
                actions.append(('find_references',{'symbol_id':name,'tests_only':target=='tests'}))
            pack=tools.retrieve_pack(s,'interviewer',topic.prompt[:600],scope_kind='private_project',read_actions=actions,save=save)
            refs=[i.reference for i in pack.items]
            topic.references=refs[:6] or topic.references
            if refs:topic.evidence_boundary=make_question_boundary(pack,topic.references,prior=topic.evidence_boundary)
            if target=='tests':
                text='请结合检索到的测试源码说明它覆盖什么、遗漏什么，并说明是否实际运行过。' if len(refs)>1 else '本次未定位到直接测试引用。你会怎样设计一个验证该函数边界的测试？不要把未找到当成项目没有测试。'
            elif target=='references':text='请结合已定位的定义与静态引用，说明调用方如何使用结果，以及哪些动态行为仍无法确认。'
            else:text='请逐句解释引用函数的输入和返回值；源码存在不代表你实际运行或参与编写过。'
            if pack.usage.budget_exhausted:text='本轮资料预算已用尽，请只说明已有原文能支持的范围，并指出仍缺什么材料。'
            if decision.focus_id in topic.followups:topic.followups[decision.focus_id]=text
        elif not s.project_id and target=='public_docs':
            # Do not show the retrieved summary or rubric while answering. Coach uses it only after finish.
            tools.retrieve_pack(s,'interviewer',topic.prompt[:600],scope_kind='public_docs',save=save)
        elif target!='none':raise WorkspaceConflict('interview_retrieval_target_out_of_scope')
        s.messages.append({'from':'interviewer','to':'coordinator','type':'retrieval_decision','turn':s.revision+1,
            'detail':'依据反馈选择下一步资料范围；工具结果已通过原始来源读取。','retrieval_target':target})
        save();return decision
