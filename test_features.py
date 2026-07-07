#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PaperCatch 功能演示脚本
测试所有核心功能是否正常工作
"""

import sys
import io
import requests
import json
import time
from datetime import datetime

# 修复 Windows 控制台编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE_URL = "http://localhost:8765"

def test_api(name, url, method="GET", data=None, expected_keys=None):
    """测试 API 端点"""
    try:
        if method == "GET":
            response = requests.get(url, timeout=10)
        elif method == "POST":
            response = requests.post(url, json=data, timeout=10)

        if response.status_code == 200:
            result = response.json()
            if expected_keys:
                missing = [k for k in expected_keys if k not in result]
                if missing:
                    print(f"❌ {name}: 缺少字段 {missing}")
                    return False
            print(f"✅ {name}: 正常")
            return True
        else:
            print(f"❌ {name}: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ {name}: {e}")
        return False

def main():
    print("=" * 60)
    print("PaperCatch 功能测试")
    print("=" * 60)
    print()

    # 1. 健康检查
    print("🔍 测试基础功能...")
    test_api(
        "健康检查",
        f"{BASE_URL}/health",
        expected_keys=["status", "service"]
    )

    # 2. 论文列表
    test_api(
        "论文列表 API",
        f"{BASE_URL}/api/papers",
        expected_keys=["papers", "total_count", "updated_at"]
    )

    # 3. 分类列表
    test_api(
        "分类列表 API",
        f"{BASE_URL}/api/categories"
    )

    # 4. 配置信息
    test_api(
        "配置信息 API",
        f"{BASE_URL}/api/config"
    )

    print()
    print("🎨 测试前端资源...")

    # 5. 前端首页
    try:
        response = requests.get(BASE_URL, timeout=10)
        if response.status_code == 200:
            # 检查中文标题
            content = response.text
            if "纸上得来" in content or "PaperCatch" in content:
                print("✅ 前端首页: 正常")
            else:
                print("❌ 前端首页: 内容异常")
        else:
            print(f"❌ 前端首页: HTTP {response.status_code}")
    except Exception as e:
        print(f"❌ 前端首页: {e}")

    print()
    print("📊 数据统计...")

    # 获取论文统计
    try:
        response = requests.get(f"{BASE_URL}/api/papers", timeout=10)
        data = response.json()
        papers = data.get("papers", [])

        print(f"  总论文数: {data.get('total_count', 0)}")
        print(f"  最后更新: {data.get('updated_at', 'N/A')}")

        if papers:
            # 分类统计
            categories = {}
            for paper in papers:
                for cat in paper.get("categories", []):
                    categories[cat] = categories.get(cat, 0) + 1

            print(f"  分类分布:")
            for cat, count in sorted(categories.items(), key=lambda x: -x[1])[:5]:
                print(f"    - {cat}: {count} 篇")

            # 评分统计
            scored = [p for p in papers if p.get("quality_score") is not None]
            if scored:
                avg_score = sum(p["quality_score"] for p in scored) / len(scored)
                print(f"  平均评分: {avg_score:.2f} ({len(scored)} 篇已评分)")
        else:
            print("  ⚠️  当前没有论文数据")
            print("     运行: python daily_pipeline.py --days 3 --max-per-cat 10")

    except Exception as e:
        print(f"  ❌ 统计失败: {e}")

    print()
    print("=" * 60)
    print("测试完成！")
    print()
    print("🌐 访问地址: http://localhost:8765")
    print("📚 使用指南: QUICKSTART.md")
    print("📝 更新日志: CHANGELOG.md")
    print("=" * 60)

if __name__ == "__main__":
    main()
