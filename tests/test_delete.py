#!/usr/bin/env python3
"""测试删除功能"""
import requests
import json

BASE = "http://localhost:8765"

print("=== 测试删除功能 ===\n")

# 1. 获取论文列表
try:
    r = requests.get(f"{BASE}/api/papers")
    data = r.json()
    papers = data.get("papers", [])
    print(f"1. 当前论文数: {len(papers)}")

    if not papers:
        print("   数据库为空，无法测试删除")
        exit(0)

    test_id = papers[-1]["arxiv_id"]  # 取最后一篇测试
    print(f"2. 测试删除 ID: {test_id}")
    print(f"   标题: {papers[-1].get('title', 'N/A')[:60]}...")

    # 2. 测试删除
    r2 = requests.delete(
        f"{BASE}/api/papers",
        json={"arxiv_ids": [test_id]},
        headers={"Content-Type": "application/json"}
    )
    result = r2.json()
    print(f"\n3. 删除响应:")
    print(f"   成功: {result.get('success')}")
    print(f"   移除数: {result.get('removed')}")

    # 3. 验证删除
    r3 = requests.get(f"{BASE}/api/papers")
    data3 = r3.json()
    papers3 = data3.get("papers", [])
    print(f"\n4. 删除后论文数: {len(papers3)}")
    print(f"   差异: {len(papers) - len(papers3)} 篇")

    if test_id not in [p["arxiv_id"] for p in papers3]:
        print(f"   ✅ 测试 ID {test_id} 已被删除")
    else:
        print(f"   ❌ 测试 ID {test_id} 仍在数据库中")

except Exception as e:
    print(f"❌ 测试失败: {e}")
