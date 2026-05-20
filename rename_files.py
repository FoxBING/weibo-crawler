#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import sys
import logging
import logging.config

if not os.path.isdir("log/"):
    os.makedirs("log/")
logging_path = os.path.split(os.path.realpath(__file__))[0] + os.sep + "logging.conf"
logging.config.fileConfig(logging_path)
logger = logging.getLogger("weibo")

ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\n\r\t#]')


def sanitize_text(text, max_len=50):
    cleaned = ILLEGAL_CHARS.sub('', text).strip()
    cleaned = re.sub(r'\s+', '_', cleaned)
    cleaned = cleaned.strip('_.')
    if not cleaned:
        cleaned = "无正文"
    return cleaned[:max_len]


def build_new_name(date_str, text, weibo_id, index, ext):
    date_compact = date_str.replace("-", "")
    snippet = sanitize_text(text)
    base = f"{date_compact}_{snippet}_{weibo_id}"
    if index is not None:
        base += f"_{index}"
    return base + ext


def heading_to_prefix(heading_time):
    return heading_time.replace(" ", "_").replace(":", "-")


def parse_md_sections(md_path):
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    sections = []
    pattern = re.compile(
        r'###\s+(.+?)\n<!--\s*weibo_id:\s*(\d+)\s*-->\n(.*?)(?=---|\Z)',
        re.DOTALL,
    )
    for m in pattern.finditer(content):
        heading_time = m.group(1).strip()
        weibo_id = m.group(2).strip()
        body = m.group(3).strip()

        date_str = heading_time[:10]
        file_prefix = heading_to_prefix(heading_time)

        text_lines = []
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith('![') or line.startswith('['):
                continue
            if line.startswith('>'):
                inner = line.lstrip('> ').strip()
                if any(kw in inner for kw in ['img/', '视频', 'Live Photo', '网页链接']):
                    continue
                text_lines.append(inner)
            else:
                text_lines.append(line)
        text = ' '.join(text_lines)

        sections.append({
            "weibo_id": weibo_id,
            "date_str": date_str,
            "file_prefix": file_prefix,
            "text": text,
        })

    return sections, content


def build_disk_index(user_dir):
    index = {}
    for root, dirs, files in os.walk(user_dir):
        for f in files:
            if f.endswith(('.md', '.csv', '.json', '.txt', '.db')):
                continue
            full_path = os.path.join(root, f)
            rel_dir = os.path.relpath(root, user_dir)
            name_no_ext = os.path.splitext(f)[0]
            ext = os.path.splitext(f)[1]
            index[f] = {
                "full_path": full_path,
                "rel_dir": rel_dir,
                "filename": f,
                "name_no_ext": name_no_ext,
                "ext": ext,
            }
    return index


def find_files_for_section(disk_index, section):
    file_prefix = section["file_prefix"]
    weibo_id = section["weibo_id"]

    matched = []
    for filename, fi in disk_index.items():
        if fi["name_no_ext"].startswith(file_prefix):
            matched.append(fi)
        elif weibo_id in fi["name_no_ext"]:
            matched.append(fi)

    return matched


def build_rename_plan(user_dir, sections):
    disk_index = build_disk_index(user_dir)
    logger.info(f"  扫描到 {len(disk_index)} 个媒体文件")

    used_files = set()
    plan = []

    for section in sections:
        matched = find_files_for_section(disk_index, section)
        matched = [fi for fi in matched if fi["filename"] not in used_files]

        weibo_id = section["weibo_id"]
        date_str = section["date_str"]
        text = section["text"]

        by_dir_ext = {}
        for fi in matched:
            key = (fi["rel_dir"], fi["ext"])
            by_dir_ext.setdefault(key, []).append(fi)

        for (rel_dir, ext), group in by_dir_ext.items():
            group.sort(key=lambda x: x["filename"])
            for i, fi in enumerate(group):
                idx = i + 1 if len(group) > 1 else None
                new_name = build_new_name(date_str, text, weibo_id, idx, ext)
                plan.append({
                    "old_path": fi["full_path"],
                    "old_name": fi["filename"],
                    "new_name": new_name,
                    "rel_dir": fi["rel_dir"],
                    "weibo_id": weibo_id,
                })
                used_files.add(fi["filename"])

    logger.info(f"  匹配: {len(plan)}, 未匹配: {len(disk_index) - len(used_files)}")
    return plan


def execute_rename(plan, dry_run=True):
    renamed = 0
    skipped = 0
    errors = 0

    for item in plan:
        old_name = item["old_name"]
        new_name = item["new_name"]
        old_path = item["old_path"]

        if old_name == new_name:
            skipped += 1
            continue

        file_dir = os.path.dirname(old_path)
        new_path = os.path.join(file_dir, new_name)

        if os.path.exists(new_path) and old_path != new_path:
            logger.warning(f"目标已存在，跳过: {new_name}")
            skipped += 1
            continue

        if dry_run:
            logger.info(f"[预览] {item['rel_dir']}/{old_name}  ->  {new_name}")
        else:
            try:
                os.rename(old_path, new_path)
                logger.info(f"[改名] {item['rel_dir']}/{old_name}  ->  {new_name}")
            except Exception as e:
                logger.error(f"[失败] {old_name}: {e}")
                errors += 1
                continue

        renamed += 1

    return renamed, skipped, errors


def update_md_references(md_path, plan, dry_run=True):
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    new_content = content
    changes = 0
    for item in plan:
        old_name = item["old_name"]
        new_name = item["new_name"]
        if old_name == new_name:
            continue
        if old_name in new_content:
            new_content = new_content.replace(old_name, new_name)
            changes += 1

    if changes == 0:
        return

    if dry_run:
        logger.info(f"[预览] {md_path}: 需更新 {changes} 处引用")
    else:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        logger.info(f"[更新] {md_path}: 更新 {changes} 处引用")


def process_user_dir(user_dir, dry_run=True):
    user_name = os.path.basename(user_dir)
    logger.info(f"{'='*60}")
    logger.info(f"处理用户: {user_name}")
    logger.info(f"模式: {'预览（不实际改名）' if dry_run else '实际改名'}")
    logger.info(f"{'='*60}")

    md_files = []
    for root, dirs, files in os.walk(user_dir):
        for f in files:
            if f.endswith('.md'):
                md_files.append(os.path.join(root, f))

    if not md_files:
        logger.warning("未找到 markdown 文件")
        return

    all_sections = []
    for md_path in md_files:
        logger.info(f"解析: {md_path}")
        sections, _ = parse_md_sections(md_path)
        logger.info(f"  找到 {len(sections)} 条微博记录")
        all_sections.extend(sections)

    if not all_sections:
        logger.warning("没有微博记录")
        return

    plan = build_rename_plan(user_dir, all_sections)
    logger.info(f"共 {len(plan)} 个文件需要改名")

    renamed, skipped, errors = execute_rename(plan, dry_run)
    logger.info(f"文件改名: {renamed} 成功, {skipped} 跳过, {errors} 失败")

    for md_path in md_files:
        update_md_references(md_path, plan, dry_run)


def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python rename_files.py preview <目录>   # 预览模式，不实际改名")
        print("  python rename_files.py apply <目录>     # 实际改名")
        print()
        print("示例:")
        print("  python rename_files.py preview test")
        print("  python rename_files.py apply test")
        print("  python rename_files.py preview weibo_data")
        sys.exit(1)

    action = sys.argv[1]
    target = sys.argv[2] if len(sys.argv) > 2 else "test"
    dry_run = action != "apply"

    script_dir = os.path.dirname(os.path.realpath(__file__))
    target_dir = os.path.join(script_dir, target)

    if not os.path.isdir(target_dir):
        logger.error(f"目录不存在: {target_dir}")
        sys.exit(1)

    user_dirs = []
    for item in sorted(os.listdir(target_dir)):
        item_path = os.path.join(target_dir, item)
        if os.path.isdir(item_path):
            user_dirs.append(item_path)

    if not user_dirs:
        logger.error(f"目录下没有用户文件夹: {target_dir}")
        sys.exit(1)

    logger.info(f"目标目录: {target_dir}")
    logger.info(f"找到 {len(user_dirs)} 个用户目录")

    for user_dir in user_dirs:
        process_user_dir(user_dir, dry_run)

    logger.info("全部处理完成")


if __name__ == "__main__":
    main()
