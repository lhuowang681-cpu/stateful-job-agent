# 8题人工核对包（当前尚未有人审核）

固定数据：expansion-final-candidates-3；SHA256 `ff6ad1d6ce4e8b0fc2346d61d6e46a0cee35540d73f4776647274ffe7fdc8d66`。

预计15—20分钟。请逐题判断：原文能否支持这个问题的候选定位？范围是否过宽？多证据是否都必要，any是否确有替代关系？无答案理由是否成立？

可回复：`编号：支持 / 需缩小范围 / 不支持 / 不确定；说明`。只有明确收到的人工逐题意见才计为人工审核；“稍后”不会改变状态。下列定位仍是AI候选，不是预先给定的真值。

开发/测试各4题。这里只核对固定合成原文，不验证个人能力或真实贡献。

## dev-final-06 · multi_evidence
入口函数到回执实现跨越哪些代码位置？

证据需求：all；检索域：project。

来源 `dev-code/app/api.py`，第3—4行：
```
def handle(key, store):
    return save_receipt(key, store)
```

来源 `dev-code/app/storage.py`，第1—6行：
```
def save_receipt(key, store):
    """Reuse a stored receipt to avoid duplicate writes."""
    if key in store:
        return store[key]
    store[key] = "done"
    return store[key]
```

## dev-final-11 · multi_evidence
从规范JSON到摘要，需要连读哪两个函数？

证据需求：all；检索域：project。

来源 `dev-code/serialize.py`，第3—4行：
```
def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

来源 `dev-code/serialize.py`，第6—8行：
```
def payload_digest(value):
    from hashlib import sha256
    return sha256(canonical(value).encode("utf-8")).hexdigest()
```

## dev-final-16 · multi_evidence
测试源码和文档一起能否证明这些断言实际运行通过？

证据需求：all；检索域：project。

来源 `dev-code/tests/test_storage.py`，第3—5行：
```
def test_duplicate():
    store = {}
    assert save_receipt("x", store) == save_receipt("x", store)
```

来源 `dev-code/docs/scope.md`，第8—9行：
```
## Verification
A test file contains source assertions. This document does not report executing those tests.
```

## dev-final-22 · unanswerable
用户独立负责该回执模块的雇佣与贡献证明存在哪里？

证据需求：all；检索域：project。

候选无答案理由：Source fixtures have no personal attribution or employment records.

## test-final-08 · multi_evidence
检查租约实现及两种拒绝断言，定位全部必要证据。

证据需求：all；检索域：project。

来源 `test-code/lease.py`，第1—2行：
```
def can_publish(current_token, attempt_token, lease_until, now):
    return current_token == attempt_token and lease_until > now
```

来源 `test-code/tests/test_lease.py`，第3—4行：
```
def test_old_token():
    assert not can_publish("new", "old", 100, 1)
```

来源 `test-code/tests/test_lease.py`，第6—7行：
```
def test_expired():
    assert not can_publish("same", "same", 1, 2)
```

## test-final-09 · documentation
从任一原文说明找到：这份租约教学样例没有实际数据库连接。

证据需求：any；检索域：project。

来源 `test-code/README.md`，第3—3行：
```
It does not connect to a database or publish messages.
```

来源 `test-code/docs/visibility.md`，第6—7行：
```
## Evidence
This fixture has no database connection and no execution logs.
```

## test-final-15 · multi_evidence
第一条记录不被允许时，如何用实现与断言验证不会占掉limit？

证据需求：all；检索域：project。

来源 `test-code/filters.py`，第1—3行：
```
def bounded_records(records, allowed_ids, limit):
    allowed = [row for row in records if row["id"] in allowed_ids]
    return allowed[:limit]
```

来源 `test-code/tests/test_filters.py`，第3—5行：
```
def test_filter_before_limit():
    rows = [{"id": "outside"}, {"id": "inside"}]
    assert bounded_records(rows, {"inside"}, 1) == [{"id": "inside"}]
```

## test-final-22 · unanswerable
部署这份样例的月度服务账单是多少？

证据需求：all；检索域：project。

候选无答案理由：No deployment, billing, or pricing record exists in the fixed corpus.

## 划分与近重复提醒
源文件/问题family机械隔离不等于语义完全独立；请同时指出问题是否只是另一题改名或同义改写。
v2候选曾把“本地事务能否涵盖任意外部操作”与测试侧的跨系统事务问题重复，AI审阅已发现；保留v2，v3把开发题改为“消费组pending与业务完成的区分”，未看测试分数后调策略。其余语义近重复仍待人工。
