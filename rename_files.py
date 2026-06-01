#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re
import sys
import logging
import logging.config
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

if not os.path.isdir("log/"):
    os.makedirs("log/")
logging_path = os.path.split(os.path.realpath(__file__))[0] + os.sep + "logging.conf"
logging.config.fileConfig(logging_path)
logger = logging.getLogger("weibo")

# 文件名非法字符：Windows 保留符号 + 换行 + #（# 在 Markdown 中会被解析为锚点，导致图片加载失败）
ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\n\r\t#]')

# Markdown 中代表媒体/链接的关键词，提取正文时需跳过
MEDIA_KEYWORDS = ('img/', '视频', 'Live Photo', '网页链接')


def sanitize_text(text: str, max_len: int = 50) -> str:
    """清理文本用于文件名：去除非法字符、合并空白、截断至指定长度"""
    cleaned = re.sub(r'<!--.*?-->', '', text)
    cleaned = ILLEGAL_CHARS.sub('', cleaned).strip()
    cleaned = re.sub(r'\s+', '_', cleaned)
    cleaned = cleaned.strip('_.')
    if not cleaned:
        cleaned = "无正文"
    return cleaned[:max_len]


def build_new_name(date_str: str, text: str, weibo_id: str,
                   index: Optional[int], ext: str) -> str:
    """按 {YYYYMMDD}_{正文前50字符}_{微博ID}_{序号}.{后缀} 规则生成新文件名"""
    date_compact = date_str.replace("-", "")
    snippet = sanitize_text(text)
    base = f"{date_compact}_{snippet}_{weibo_id}"
    if index is not None:
        base += f"_{index}"
    return base + ext


def heading_to_prefix(heading_time: str) -> str:
    """将 Markdown 标题中的时间戳转为文件名前缀格式，如 '2026-03-25 09:29:53' → '2026-03-25_09-29-53'"""
    return heading_time.replace(" ", "_").replace(":", "-")


def _is_media_line(line: str) -> bool:
    """判断一行 Markdown 是否为媒体/链接行，提取正文时应跳过"""
    if line.startswith('![') or line.startswith('['):
        return True
    if line.startswith('<video'):
        return True
    if line.startswith('>'):
        inner = line.lstrip('> ').strip()
        if any(kw in inner for kw in MEDIA_KEYWORDS):
            return True
    return False


def _extract_text_from_body(body: str) -> str:
    """从微博 Markdown 正文中提取纯文本，去除图片/视频/链接等媒体行"""
    text_lines: List[str] = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('<!--'):
            continue
        if _is_media_line(line):
            continue
        # 引用块中的非媒体内容保留（如转发正文）
        if line.startswith('>'):
            text_lines.append(line.lstrip('> ').strip())
        else:
            text_lines.append(line)
    return ' '.join(text_lines)


def parse_md_sections(md_path: str) -> Tuple[List[Dict], str]:
    """解析 Markdown 文件，提取每条微博的元数据（时间戳、ID、正文）"""
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    sections: List[Dict] = []
    pattern = re.compile(
        r'###\s+(.+?)\n<!--\s*weibo_id:\s*(\d+)\s*-->\n(.*?)(?=---|\Z)',
        re.DOTALL,
    )
    for m in pattern.finditer(content):
        heading_time = m.group(1).strip()
        weibo_id = m.group(2).strip()
        body = m.group(3).strip()

        sections.append({
            "weibo_id": weibo_id,
            "date_str": heading_time[:10],
            "file_prefix": heading_to_prefix(heading_time),
            "text": _extract_text_from_body(body),
        })

    return sections, content


def build_disk_index(user_dir: str) -> Dict[str, Dict]:
    """扫描用户目录下所有媒体文件，返回 {文件名: 文件信息} 索引"""
    index: Dict[str, Dict] = {}
    skip_exts = ('.md', '.csv', '.json', '.txt', '.db')
    for root, _, files in os.walk(user_dir):
        for f in files:
            if f.endswith(skip_exts):
                continue
            full_path = os.path.join(root, f)
            name_no_ext, ext = os.path.splitext(f)
            index[f] = {
                "full_path": full_path,
                "rel_dir": os.path.relpath(root, user_dir),
                "filename": f,
                "name_no_ext": name_no_ext,
                "ext": ext,
            }
    return index


def build_prefix_index(disk_index: Dict[str, Dict]) -> Dict[str, List[Dict]]:
    """预建前缀索引：{name_no_ext → [file_info]}，用于按前缀快速查找文件

    因为同一 name_no_ext 不会重复（文件名唯一），所以每个 key 只有一个条目，
    但返回 List 以保持接口一致性。
    """
    prefix_map: Dict[str, List[Dict]] = defaultdict(list)
    for fi in disk_index.values():
        prefix_map[fi["name_no_ext"]].append(fi)
    return prefix_map


def find_files_for_section(prefix_index: Dict[str, List[Dict]],
                           weibo_id_set: Set[str],
                           section: Dict) -> List[Dict]:
    """根据时间戳前缀或微博 ID 匹配磁盘文件

    使用预建的前缀索引替代逐项线性扫描，将匹配复杂度从 O(n×m) 降至 O(k)，
    其中 k 为匹配到的文件数。
    """
    file_prefix = section["file_prefix"]
    weibo_id = section["weibo_id"]

    matched: List[Dict] = []
    # 路径1：按时间戳前缀匹配（如 '2026-03-25_09-29-53'）
    for name_no_ext, fi_list in prefix_index.items():
        if name_no_ext.startswith(file_prefix):
            matched.extend(fi_list)

    # 路径2：按微博 ID 匹配（兜底，覆盖前缀未命中的旧命名文件）
    if weibo_id in weibo_id_set:
        for name_no_ext, fi_list in prefix_index.items():
            if weibo_id in name_no_ext and not name_no_ext.startswith(file_prefix):
                matched.extend(fi_list)

    return matched


def build_rename_plan(user_dir: str, sections: List[Dict]) -> List[Dict]:
    """为所有微博段构建重命名计划：匹配文件 → 按目录和扩展名分组 → 生成新文件名"""
    disk_index = build_disk_index(user_dir)
    prefix_index = build_prefix_index(disk_index)
    # 预计算所有出现的微博 ID，避免 find_files_for_section 中重复扫描
    weibo_id_set: Set[str] = {s["weibo_id"] for s in sections}

    logger.info(f"  扫描到 {len(disk_index)} 个媒体文件")

    used_files: Set[str] = set()
    plan: List[Dict] = []

    for section in sections:
        matched = find_files_for_section(prefix_index, weibo_id_set, section)
        matched = [fi for fi in matched if fi["filename"] not in used_files]

        weibo_id = section["weibo_id"]
        date_str = section["date_str"]
        text = section["text"]

        # 按目录+扩展名分组，同组内按文件名排序后分配序号
        by_dir_ext: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
        # 检测该微博是否在 live_photo 目录下有 .mov 文件
        has_live_photo_mov = any(
            fi["ext"] == ".mov" and "Live Photo" in fi["rel_dir"]
            for fi in matched
        )
        for fi in matched:
            # 如果 live_photo 目录已有 .mov，跳过 img 下的重复 .mov
            if fi["ext"] == ".mov" and fi["rel_dir"].startswith("img") and has_live_photo_mov:
                continue
            key = (fi["rel_dir"], fi["ext"])
            by_dir_ext[key].append(fi)

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


def execute_rename(plan: List[Dict], dry_run: bool = True) -> Tuple[int, int, int]:
    """执行重命名计划，返回 (成功数, 跳过数, 失败数)"""
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

        new_path = os.path.join(os.path.dirname(old_path), new_name)

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


def update_md_references(md_path: str, plan: List[Dict],
                         dry_run: bool = True) -> None:
    """更新 Markdown 中的媒体引用：直接用文件的实际路径替换旧引用

    不关心旧引用写了什么，按微博段逐个重建：提取该段内所有非 http 引用，
    按扩展名和出现顺序与 plan 中同微博 ID、同扩展名的文件一一配对，
    用文件实际路径（rel_dir/new_name）写回。
    视频类文件（.mov/.mp4）使用 <video> 嵌入语法替代链接语法，支持内嵌播放。
    """
    VIDEO_EXTS = ('.mov', '.mp4')

    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    # plan 中文件改名后需要更新引用的条目，按 weibo_id 分组
    plan_by_weibo: Dict[str, List[Dict]] = defaultdict(list)
    for item in plan:
        plan_by_weibo[item["weibo_id"]].append(item)

    # 按微博段逐段处理，用正则替换每段内的引用路径
    section_pattern = re.compile(
        r'(###\s+.+?\n<!--\s*weibo_id:\s*(\d+)\s*-->\n)(.*?)(?=---|\Z)',
        re.DOTALL,
    )
    # 匹配链接语法 [text](path) 和视频嵌入 <video src="path" ...>
    ref_pattern = re.compile(r'(\[.*?\]\()(?!http)(.*?)(\))')
    video_pattern = re.compile(r'(<video\s+src=["\'])(.*?)(["\'].*?</video>)', re.DOTALL)

    new_content = content
    changes = 0

    for m in section_pattern.finditer(content):
        weibo_id = m.group(2).strip()
        plan_items = plan_by_weibo.get(weibo_id)
        if not plan_items:
            continue

        # plan 条目按 (rel_dir, ext) 分组，组内排序（与 build_rename_plan 一致）
        by_dir_ext: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
        for item in plan_items:
            ext = os.path.splitext(item["new_name"])[1]
            by_dir_ext[(item["rel_dir"], ext)].append(item)

        # 展平为按扩展名分组的新路径列表：先 .jpg 再 .mov 再 .mp4
        new_refs_by_ext: Dict[str, List[str]] = defaultdict(list)
        for (rel_dir, ext), group in sorted(by_dir_ext.items()):
            group.sort(key=lambda x: x["new_name"])
            for item in group:
                new_path = item["rel_dir"].replace("\\", "/") + "/" + item["new_name"]
                new_refs_by_ext[ext].append(new_path)

        # 消费计数器：每个扩展名独立计数
        consume_idx: Dict[str, int] = defaultdict(int)

        body = m.group(3)
        new_body = body

        # 处理已有的 <video> 标签（仅更新路径）
        for vm in video_pattern.finditer(body):
            old_path = vm.group(2)
            ref_ext = os.path.splitext(old_path)[1]
            idx = consume_idx[ref_ext]
            ref_list = new_refs_by_ext.get(ref_ext, [])
            if idx < len(ref_list) and old_path != ref_list[idx]:
                old_full = vm.group(1) + old_path + vm.group(3)
                new_full = vm.group(1) + ref_list[idx] + vm.group(3)
                new_body = new_body.replace(old_full, new_full, 1)
                changes += 1
                consume_idx[ref_ext] += 1
            elif idx < len(ref_list):
                consume_idx[ref_ext] += 1

        # 处理链接语法 [text](path)
        for ref_match in ref_pattern.finditer(body):
            old_path = ref_match.group(2)
            ref_ext = os.path.splitext(old_path)[1]
            idx = consume_idx[ref_ext]
            ref_list = new_refs_by_ext.get(ref_ext, [])
            if idx < len(ref_list):
                new_path = ref_list[idx]
                old_full = ref_match.group(1) + old_path + ref_match.group(3)
                # 视频文件用 <video> 嵌入语法
                if ref_ext in VIDEO_EXTS:
                    new_full = f'<video src="{new_path}" controls></video>'
                else:
                    new_full = ref_match.group(1) + new_path + ref_match.group(3)
                if old_full != new_full:
                    new_body = new_body.replace(old_full, new_full, 1)
                    changes += 1
                consume_idx[ref_ext] += 1

        if new_body != body:
            new_content = new_content.replace(body, new_body, 1)

    if changes == 0:
        return

    if dry_run:
        logger.info(f"[预览] {md_path}: 需更新 {changes} 处引用")
    else:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        logger.info(f"[更新] {md_path}: 更新 {changes} 处引用")


def reorder_live_photos(md_path: str, dry_run: bool = True) -> None:
    """将 Markdown 中散落的 Live Photo <video> 标签移到对应图片下方，使图文成对排列

    处理流程：
    1. 收集所有未被标记处理的 <video> 标签，按文件名建立索引
    2. 从原文中删除这些散落的视频标签
    3. 遍历图片引用，若匹配到同名视频则插入到图片下方并标记已处理
    """
    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()

    unprocessed_pattern = re.compile(
        r'(<video src="live_photo/[^"]+/([^"]+)\.mov" controls></video>)'
        r'(?!\s*<!-- processed_live_photo -->)'
    )
    new_videos = unprocessed_pattern.findall(text)
    video_dict: Dict[str, str] = {name: tag for tag, name in new_videos}

    if not video_dict:
        return

    # 删除所有未被标记处理的散落视频标签及尾部空白
    text = re.sub(
        r'<video src="live_photo/[^"]+\.mov" controls></video>\s*'
        r'(?!\s*<!-- processed_live_photo -->)',
        '',
        text,
    )

    def replacer(match: re.Match) -> str:
        full_match = match.group(0)
        img_tag = match.group(1)
        img_name = match.group(2)

        if "<!-- processed_live_photo -->" in full_match:
            return full_match

        if img_name in video_dict:
            return f"{img_tag}\n{video_dict[img_name]}\n<!-- processed_live_photo -->"

        return full_match

    image_pattern = re.compile(
        r'(!\[img\]\(img/([^)]+)\.jpg\))'
        r'(?:[\s\n]*<video.*?</video>[\s\n]*<!-- processed_live_photo -->)?'
    )
    final_text = image_pattern.sub(replacer, text)

    if final_text == text:
        return

    if dry_run:
        logger.info(f"[预览] {md_path}: 需调整 {len(video_dict)} 个 Live Photo 顺序")
    else:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(final_text)
        logger.info(f"[调整] {md_path}: 已调整 {len(video_dict)} 个 Live Photo 顺序")


def _collect_md_files(user_dir: str) -> List[str]:
    """递归收集用户目录下所有 Markdown 文件"""
    md_files: List[str] = []
    for root, _, files in os.walk(user_dir):
        for f in files:
            if f.endswith('.md'):
                md_files.append(os.path.join(root, f))
    return md_files


def process_user_dir(user_dir: str, dry_run: bool = True) -> None:
    """处理单个用户目录：解析 MD → 构建重命名计划 → 执行改名 → 更新引用"""
    user_name = os.path.basename(user_dir)
    logger.info(f"{'='*60}")
    logger.info(f"处理用户: {user_name}")
    logger.info(f"模式: {'预览（不实际改名）' if dry_run else '实际改名'}")
    logger.info(f"{'='*60}")

    md_files = _collect_md_files(user_dir)
    if not md_files:
        logger.warning("未找到 markdown 文件")
        return

    all_sections: List[Dict] = []
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
        reorder_live_photos(md_path, dry_run)


def main() -> None:
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

    user_dirs = [
        os.path.join(target_dir, item)
        for item in sorted(os.listdir(target_dir))
        if os.path.isdir(os.path.join(target_dir, item))
    ]

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
