#!/usr/bin/env python3
"""
从PDF提取高亮和注释
用法: python extract_annotations.py <pdf_file> [output_file]
"""

import fitz  # PyMuPDF
import sys
from pathlib import Path


def extract_annotations(pdf_path: str) -> list:
    """提取PDF中的所有注释"""
    doc = fitz.open(pdf_path)
    all_annotations = []

    for page_num, page in enumerate(doc, start=1):
        annots = page.annots()
        if annots is None:
            continue

        for annot in annots:
            annot_info = {
                "page": page_num,
                "type": annot.type[1],  # 类型名称 (Highlight, Text, etc.)
                "rect": list(annot.rect),  # 位置
            }

            # 获取高亮文本
            if annot.type[0] == 8:  # PAGE_HIGHLIGHT
                # 获取高亮区域的文本
                text_in_rect = page.get_text(clip=annot.rect).strip()
                annot_info["highlighted_text"] = text_in_rect

            # 获取批注内容
            if annot.info:
                annot_info["author"] = annot.info.get("author", "")
                annot_info["content"] = annot.info.get("content", "")
                annot_info["title"] = annot.info.get("title", "")

            # 获取弹窗注释
            if annot.type[0] == 10:  # PAGE_TEXT (弹窗注释)
                annot_info["content"] = annot.info.get("content", "")

            all_annotations.append(annot_info)

    doc.close()
    return all_annotations


def format_output(annotations: list) -> str:
    """格式化输出"""
    if not annotations:
        return "未找到注释"

    lines = []
    lines.append("=" * 80)
    lines.append(f"PDF注释提取 - 共 {len(annotations)} 条注释")
    lines.append("=" * 80)
    lines.append("")

    # 按页分组
    pages = {}
    for annot in annotations:
        page = annot["page"]
        if page not in pages:
            pages[page] = []
        pages[page].append(annot)

    for page_num in sorted(pages.keys()):
        lines.append("=" * 80)
        lines.append(f"第 {page_num} 页")
        lines.append("=" * 80)
        lines.append("")

        for i, annot in enumerate(pages[page_num], 1):
            lines.append(f"【注释 {i}】[{annot['type']}]")
            lines.append("-" * 60)

            if "highlighted_text" in annot and annot["highlighted_text"]:
                lines.append(f"高亮文本: {annot['highlighted_text']}")

            if annot.get("content"):
                lines.append(f"批注内容: {annot['content']}")

            lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("用法: python extract_annotations.py <pdf_file> [output_file]")
        print("\n示例:")
        print("  python extract_annotations.py paper.pdf")
        print("  python extract_annotations.py paper.pdf annotations.txt")
        sys.exit(1)

    pdf_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    if not Path(pdf_path).exists():
        print(f"错误: 文件不存在: {pdf_path}")
        sys.exit(1)

    print(f"正在提取注释: {pdf_path}")
    annotations = extract_annotations(pdf_path)
    output = format_output(annotations)

    if output_path:
        Path(output_path).write_text(output, encoding="utf-8")
        print(f"注释已保存到: {output_path}")
    else:
        print(output)


if __name__ == "__main__":
    main()