# Job Agent Demo

这是一条适合面试现场快速讲解的完整、脱敏工作流。机器可读结果位于 [`tests/fixtures/job_search_workflow/demo_result.json`](../tests/fixtures/job_search_workflow/demo_result.json)。

## 1. Profile

| Preference | Value |
| --- | --- |
| City | 杭州 |
| Direction | Agent / 大模型应用 |
| Job type | 实习 |

输入岗位：`Example AI` 的“杭州 Agent 实习岗位”。

## 2. JD Analysis

Requirement Analyzer 将 JD 拆成四个可独立评估的要求：

1. Agent Runtime 与 Tool Calling
2. RAG / 语义检索
3. 可恢复的异步 Agent 后端
4. Kubernetes 生产集群运维

城市、方向和岗位类型与长期偏好匹配；这些 preference 结论与技术证据分开保存。

## 3. Retrieval and Evidence

Runtime 注册并调用 `career.query_candidate_evidence`，调用经过 Tool Registry、Policy、Budget、Timeout 和 Trajectory，再由 MCP Adapter / Bridge 到达 Career Knowledge Service。

| Requirement | Candidate-owned source | Assessment |
| --- | --- | --- |
| Agent Runtime / Tool Calling | `real-agent-runtime-governance` | evidence lead |
| RAG / semantic retrieval | `real-dense-knowledge-retrieval` | evidence lead |
| Async backend / recovery | `real-backend-reliability` | evidence lead |
| Kubernetes operations | none | gap |

项目材料当前属于 C1 provenance，因此真实模型中的正向结果正式状态是 `unverified_lead`，而不是被包装成已验证事实。每条 evidence 仍保留 document、chunk、exact source span 和 retrieval metadata。

## 4. Governed Tracking

JobMatchAnalysis 完成后，写操作不会绕过 Runtime：

```text
user approval
→ application.record
→ to_apply
→ ops.apply_transition
→ applied
→ resume_screen
→ first_interview
```

最终 tracker 状态是 `first_interview`，历史保留：

```text
to_apply → applied → resume_screen → first_interview
```

重复 resume/retry 使用稳定 action identity 与 tracker 保护，避免产生重复 transition。

## 5. Interview Preparation

进入面试阶段后，系统再次通过受治理的 MCP retrieval 刷新相关项目材料，并生成四类岗位相关追问：

- Agent Runtime / Tool Calling
- MCP integration
- RAG retrieval and evaluation
- Async backend and recovery

Kubernetes 仍作为风险与复习项呈现，不会因为检索到了相邻后端材料而伪造成候选人经验。

## 6. Reproduce the deterministic demo

```bash
python -m pip install -e ".[dev]"
python -m pytest -q tests/test_end_to_end_job_search_workflow.py
```

该测试使用 deterministic model fixture 验证完整业务合同。真实 Qwen generation + embedding 路径是单独的验证，运行方式见根目录 README；两者的结果不会混在一起表述。
