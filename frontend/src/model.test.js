import test from 'node:test';
import assert from 'node:assert/strict';
import { factFields, changedFields, extractionSummary, quoteParts } from './model.js';
import { matchLabel } from './matching.js';
import { collaborationStatus, canAcceptCollaboration, relevanceLabel } from './collaboration.js';
const doc = {personal: {name: {text: '测试', source: {start: 0, end: 2}}}, skills: [{text: 'Python', source: {}}]};
test('flatten factual leaves without treating structural labels as facts', () => {
  assert.deepEqual(Object.keys(factFields(doc)), ['personal.name', 'skills.0']);
});
test('submit only explicit additions, changes and removals', () => {
  assert.deepEqual(changedFields(doc, {'personal.name': '测试', 'skills.0': '', 'skills.1': 'SQL'}),
    [{path: 'skills.0', value: ''}, {path: 'skills.1', value: 'SQL'}]);
});
test('source highlights use Unicode characters rather than UTF-16 code units', () => {
  assert.deepEqual(quoteParts('甲😀Python乙', {start: 2, end: 8}), ['甲😀', 'Python', '乙']);
});
test('HTML-like text stays plain data', () => {
  assert.deepEqual(quoteParts('<script>alert(1)</script>', {start: 0, end: 8})[1], '<script>');
});
test('autofill summary counts extracted fields and entries without inventing coverage', () => {
  assert.deepEqual(extractionSummary({...doc, projects: [{name: {text: '项目', source: {}}}]}),
    {fields: 3, education: 0, experience: 0, projects: 1, skills: 1});
});
test('an empty draft reports zero extraction rather than successful completion', () => {
  assert.deepEqual(extractionSummary({personal: {name: null}}),
    {fields: 0, education: 0, experience: 0, projects: 0, skills: 0});
});
test('local keyword hits never display verified support', () => {
  assert.equal(matchLabel({links:[{}],match_status:'supported'},'local_check'),'待核对线索');
  assert.equal(matchLabel({links:[],match_status:'gap'},'local_check'),'未定位线索');
});
test('C1 semantic support retains independent-verification boundary', () => {
  assert.equal(matchLabel({links:[{}],match_status:'unverified_lead'},'llm'),'简历自述 · 未独立核实');
});
test('conflict is visible even when the row has positive links', () => {
  assert.equal(matchLabel({links:[{}],match_status:'unverified_lead',has_contradiction:true},'llm'),'冲突或范围限制 · 待核对');
});
test('collaboration approval requires reviewed state, current version and saved editor',()=>{
  const v={version_id:'v2'}, view={can_apply:true,state:{status:'awaiting_approval'},expected_head_version_id:'v2'};
  assert.equal(canAcceptCollaboration(view,v,false),true);
  assert.equal(canAcceptCollaboration(view,v,true),false);
  assert.equal(canAcceptCollaboration(view,{version_id:'v1'},false),false);
  assert.equal(canAcceptCollaboration({...view,state:{status:'needs_input'}},v,false),false);
});
test('uncertain model invocation has an explicit no-replay label',()=>{
  assert.match(collaborationStatus({status:'running',model_inflight:true}),/禁止自动重放/);
  assert.match(collaborationStatus({status:'awaiting_approval'}),/等待你核对/);
});
test('keyword lead and model recommendation do not claim independently verified truth',()=>{
  assert.match(relevanceLabel('keyword_lead'),/仅关键词/);
  assert.match(relevanceLabel('model_recommends'),/非事实证明/);
  assert.doesNotMatch(collaborationStatus({status:'awaiting_approval'}),/核验通过|事实.*通过/);
});
test('partial or unclear context is displayed separately from recommendation',()=>{
  assert.equal(relevanceLabel('needs_input'),'需补上下文');
  assert.equal(relevanceLabel('revise'),'建议改选');
  assert.equal(relevanceLabel('not_reviewed'),'尚未评审');
});
