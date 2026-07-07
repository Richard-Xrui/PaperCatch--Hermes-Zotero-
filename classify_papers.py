#!/usr/bin/env python3
"""Smart paper classification. Uses keyword matching + AI fallback."""
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "papers_database.json"
CATS_PATH = BASE_DIR / "papercatch_categories.json"

# Category matching rules (internal, for auto-classification only)
CAT_RULES = {
    "llm": ["llm", "language model", "transformer", "gpt", "agent", "智能体", "prompt", "alignment", "对齐", "safety", "安全", "rlhf", "unlearning", "遗忘", "reasoning", "推理", "verification", "验证", "tool", "工具"],
    "cv": ["vision", "视觉", "image", "图像", "video", "视频", "recognition", "识别", "detection", "检测", "segmentation", "分割", "face", "人脸", "vlm", "多模态", "multimodal", "camera", "相机"],
    "ml": ["machine learning", "机器学习", "training", "训练", "distillation", "蒸馏", "optimization", "优化", "gradient", "梯度", "classification", "分类", "regression", "回归", "ensemble", "集成", "tabular", "表格", "grpo", "reinforcement learning", "强化学习"],
    "3d": ["3d", "三维", "reconstruction", "重建", "geometry", "几何", "point cloud", "点云", "gaussian splatting", "3dgs", "depth", "深度", "novel view", "新视角", "4d", "scene", "场景", "spatial", "空间"],
    "robot": ["robot", "机器人", "manipulation", "操作", "grasp", "抓取", "autonomous", "自动驾驶", "navigation", "导航", "vla", "tactile", "触觉", "deformable", "可变形", "world model", "世界模型", "policy", "策略"],
    "generate": ["generation", "生成", "diffusion", "扩散", "gan", "vae", "video generation", "视频生成", "image generation", "图像生成", "generative"],
    "medical": ["medical", "医学", "clinical", "临床", "diagnosis", "诊断", "drug", "药物", "chemistry", "化学", "astronomy", "天文", "physics", "物理", "biology", "生物", "ct", "mri", "aneurysm", "动脉瘤", "healthcare", "医疗", "patient", "患者"],
    "code": ["program", "程序", "code", "代码", "symbolic", "符号", "synthesis", "合成", "software", "软件", "programming", "编程", "compiler", "编译器"],
    "efficient": ["efficient", "效率", "compression", "压缩", "acceleration", "加速", "quantization", "量化", "pruning", "剪枝", "lightweight", "轻量", "token reduction", "蒸馏"],
    "benchmark": ["benchmark", "基准", "evaluation", "评估", "test", "测试", "diagnose", "诊断", "comparison", "比较", "dataset", "数据集", "survey", "综述"],
}

def classify(paper):
    text = (paper.get("title","") + " " + paper.get("abstract","") + " " + (paper.get("title_cn","")) + " " + (paper.get("abstract_cn",""))).lower()
    
    scores = {}
    for cat_id, keywords in CAT_RULES.items():
        score = sum(1 for kw in keywords if kw in text)
        if score > 0:
            scores[cat_id] = score
    
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    
    # Return top 2 matches
    result = []
    for cat_id, _ in ranked[:2]:
        label = next((c["label"] for c in CATEGORIES if c["id"] == cat_id), cat_id)
        result.append({"id": cat_id, "label": label, "zotero_path": "PaperCatch/" + label})
    
    if not result:
        result = [{"id": "llm", "label": "大语言模型", "zotero_path": "PaperCatch/大语言模型"}]
    return result


if not CATS_PATH.exists():
    print("No categories file")
    exit(0)

with open(CATS_PATH, "r", encoding="utf-8") as f:
    CATEGORIES = json.load(f)

with open(DB_PATH, "r", encoding="utf-8") as f:
    db = json.load(f)

count = 0
for p in db.get("papers", []):
    p["papercatch_cats"] = classify(p)
    count += 1

with open(DB_PATH, "w", encoding="utf-8") as f:
    json.dump(db, f, ensure_ascii=False, indent=2)

print(f"Classified {count} papers")
