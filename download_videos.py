#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
视频独立下载脚本：读取 video_links.txt，用 yt-dlp 下载到 upstream 一致的位置。

配合 weibo.py 的 write_video_links() 使用：
  - weibo.py 爬取时把 video.weibo.com/show?fid=xxx 永久链接写入
    {output_directory}/video_links.txt
  - 本脚本读取该 txt，用 yt-dlp 下载，成功后移入 video_links.done.txt

格式（每行 6 个字段，用 " | " 分隔）：
    微博ID | 发布时间 | 用户名 | 类型 | 目标路径(相对output_directory) | URL

用法：
    python download_videos.py                    # 下载 weibo_data/video_links.txt
    python download_videos.py --txt 路径.txt     # 指定 txt 路径
    python download_videos.py --limit 5          # 只下载前 5 条
    python download_videos.py --dry-run          # 只打印不下载
"""

import argparse
import os
import shlex
import sys
import tempfile
from typing import List, Optional, Tuple

try:
    from yt_dlp import YoutubeDL
except ImportError:
    print("未安装 yt-dlp，请先运行: pip install yt-dlp", file=sys.stderr)
    sys.exit(1)


def to_netscape_cookie(cookie_str: str, domain: str = ".weibo.com") -> str:
    """把浏览器字符串 cookie 转成 yt-dlp 需要的 Netscape 格式。

    输入: "SUB=xxx; SUBP=yyy; M_WEIBOCN_PARAMS=zzz"
    输出: Netscape cookies.txt 格式（7 列 tab 分隔）
    所有 cookie 项归一到 domain 下，Include Subdomains=TRUE，
    Path=/，Secure=FALSE（微博 m 站视频用 http/https 都能下）。
    """
    lines = ["# Netscape HTTP Cookie File", "# 由 download_videos.py 自动转换"]
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        name, value = name.strip(), value.strip()
        if not name:
            continue
        # 字段顺序: domain, include_subdomains, path, secure, expiration, name, value
        lines.append(f"{domain}\tTRUE\t/\tFALSE\t0\t{name}\t{value}")
    return "\n".join(lines) + "\n"


def prepare_cookie_file(cookie_arg: str) -> Optional[str]:
    """解析 --cookies 参数，返回可用的 cookies 文件路径。

    支持三种情况:
    1. 空：返回 None（不使用 cookie）
    2. 文件存在且是 Netscape 格式：直接返回该路径
    3. 文件存在但是浏览器字符串格式：转成 Netscape 写临时文件返回

    weibo.py 使用的 cookie.txt 是 "key=value; key=value" 字符串格式，
    而 yt-dlp 的 --cookies 需要 Netscape 格式，因此必须转换。
    """
    if not cookie_arg:
        return None
    if not os.path.isfile(cookie_arg):
        print(f"[警告] cookie 文件不存在: {cookie_arg}，将不带 cookie 下载", file=sys.stderr)
        return None

    with open(cookie_arg, "r", encoding="utf-8") as f:
        raw = f.read().strip()

    # Netscape 格式特征：首行是 # Netscape HTTP Cookie File 或包含 \t
    if raw.startswith("# Netscape") or "\t" in raw:
        return cookie_arg

    # 浏览器字符串格式，转换并写临时文件
    netscape = to_netscape_cookie(raw)
    tmp_fd, tmp_path = tempfile.mkstemp(prefix="weibo_cookies_", suffix=".txt")
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
        f.write(netscape)
    print(f"[cookie] 已将 {cookie_arg} 转换为 Netscape 格式临时文件")
    return tmp_path


def cleanup_cookie_file(cookie_path: Optional[str], converted: bool) -> None:
    """如果是转换生成的临时文件，删除它"""
    if converted and cookie_path and os.path.isfile(cookie_path):
        try:
            os.remove(cookie_path)
        except OSError:
            pass


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    p = argparse.ArgumentParser(
        description="读取 video_links.txt，用 yt-dlp 下载视频到 upstream 一致的位置"
    )
    p.add_argument(
        "--txt", default="weibo_data/video_links.txt",
        help="video_links.txt 路径（默认: weibo_data/video_links.txt）",
    )
    p.add_argument(
        "--output-dir", default="weibo_data",
        help="txt 中目标路径相对的 output_directory（默认: weibo_data）",
    )
    p.add_argument(
        "--limit", type=int, default=0,
        help="最多下载的条数，0 表示全部（默认: 0）",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="只打印将要下载的内容，不实际下载",
    )
    p.add_argument(
        "--cookies", default="pcwb.txt",
        help="yt-dlp 使用的 cookies 文件路径（默认: pcwb.txt，"
             "需提供 weibo.com PC站登录态的 cookie）",
    )
    return p.parse_args()


def parse_line(line: str) -> Optional[Tuple[str, str, str, str, str, str]]:
    """解析 txt 的一行，返回 (id, time, user, type, path, url)；非数据行返回 None。

    格式: 微博ID | 发布时间 | 用户名 | 类型 | 目标路径 | URL
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 6:
        return None
    weibo_id, created_at, user, type_label, rel_path, url = parts[:6]
    if not url.startswith("http"):
        return None
    return weibo_id, created_at, user, type_label, rel_path, url


def load_entries(txt_path: str) -> List[Tuple[str, str, str, str, str, str]]:
    """读取 txt 中所有待下载条目"""
    if not os.path.isfile(txt_path):
        print(f"[错误] 找不到 {txt_path}", file=sys.stderr)
        sys.exit(1)
    entries = []
    with open(txt_path, "r", encoding="utf-8") as f:
        for line in f:
            item = parse_line(line)
            if item:
                entries.append(item)
    return entries


def build_ydl_opts(out_path: str, cookies: str) -> dict:
    """构建 yt-dlp 选项。

    out_path: 最终输出文件路径（含扩展名）
    cookies:  cookies.txt 路径，空则不使用
    """
    # outtmpl 直接指定完整路径，yt-dlp 默认会保留原扩展名；
    # 因 weibo 的 fid 链接无文件名，这里显式给出文件名（不含扩展名），
    # 由 merge_output_format 保证最终落到指定扩展名。
    base, _ = os.path.splitext(out_path)
    opts = {
        "outtmpl": base + ".%(ext)s",
        "merge_output_format": "mp4",
        "noprogress": False,
        "retries": 5,
        "fragment_retries": 5,
        "quiet": False,
        "no_warnings": False,
    }
    if cookies:
        opts["cookiefile"] = cookies
    return opts


def _try_download(url: str, abs_path: str, cookies: str) -> bool:
    """单次尝试用 yt-dlp 下载，返回是否生成了目标文件。

    cookies 为空时走游客模式（yt-dlp 的 WeiboVideo 提取器会自动获取 guest cookie）；
    非空时附加 cookie 文件走登录态下载。
    """
    try:
        opts = build_ydl_opts(abs_path, cookies)
        with YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as e:
        print(f"         yt-dlp 异常: {e}", file=sys.stderr)
        return False

    # yt-dlp 可能输出不同扩展名（.mp4/.mkv），检查是否产生了任何文件
    base, _ = os.path.splitext(abs_path)
    candidates = [base + ext for ext in (".mp4", ".mkv", ".webm", ".mov")]
    return any(os.path.isfile(c) for c in candidates)


def download_one(entry: Tuple[str, str, str, str, str, str],
                 output_dir: str, cookies: str, dry_run: bool) -> bool:
    """下载单条视频，成功返回 True。

    策略：优先游客模式（不消耗登录态），失败再回退到 cookie 模式。
    entry: (id, time, user, type, rel_path, url)
    成功判定：目标文件最终存在（yt-dlp 下载完成或已存在）。
    """
    weibo_id, created_at, user, type_label, rel_path, url = entry
    # 拼接绝对输出路径，与 weibo.py 的目录约定一致
    abs_path = os.path.join(output_dir, rel_path.replace("/", os.sep))
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)

    # 已存在则视为成功，便于多次运行幂等
    if os.path.isfile(abs_path):
        print(f"[跳过] 已存在: {abs_path}")
        return True

    print(f"[下载] {weibo_id} | {user} | {type_label}")
    print(f"       URL:  {url}")
    print(f"       目标: {abs_path}")

    if dry_run:
        return False

    # 第一步：游客模式（不传 cookie）
    print("       [1/2] 尝试游客模式...")
    if _try_download(url, abs_path, ""):
        print(f"       [1/2] 游客模式成功")
        return True

    # 第二步：游客失败，回退 cookie 模式
    if not cookies:
        print(f"[失败] {weibo_id}: 游客模式失败，且未提供 cookie", file=sys.stderr)
        return False

    # 游客模式可能留下半成品，清理后重试
    base, _ = os.path.splitext(abs_path)
    for ext in (".mp4", ".mkv", ".webm", ".mov", ".part", ".ytdl"):
        tmp = base + ext
        if os.path.isfile(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass

    print("       [2/2] 游客模式失败，改用 cookie 模式...")
    if _try_download(url, abs_path, cookies):
        print(f"       [2/2] cookie 模式成功")
        return True

    print(f"[失败] {weibo_id}: 游客和 cookie 模式均失败", file=sys.stderr)
    return False


def move_to_done(txt_path: str, done_path: str,
                 succeeded: List[Tuple[str, str, str, str, str, str]]) -> None:
    """把成功的条目从 txt 移到 done 文件，保持 txt 只剩待下载项。"""
    if not succeeded:
        return
    succ_urls = {entry[5] for entry in succeeded}

    # 1. 成功条目追加到 done 文件
    with open(done_path, "a", encoding="utf-8") as f:
        if os.path.getsize(done_path) == 0:
            f.write("# video_links.done.txt - 已成功下载的视频链接\n")
        for entry in succeeded:
            weibo_id, created_at, user, type_label, rel_path, url = entry
            f.write(f"{weibo_id} | {created_at} | {user} | {type_label} | {rel_path} | {url}\n")

    # 2. 重写 txt，剔除成功条目
    remaining = []
    if os.path.isfile(txt_path):
        with open(txt_path, "r", encoding="utf-8") as f:
            for line in f:
                item = parse_line(line)
                if item and item[5] in succ_urls:
                    continue
                remaining.append(line.rstrip("\n"))
    with open(txt_path, "w", encoding="utf-8") as f:
        for line in remaining:
            f.write(line + "\n")
    print(f"[归档] {len(succeeded)} 条已移入 {done_path}")


def main() -> None:
    """脚本入口"""
    args = parse_args()
    txt_path = args.txt
    done_path = os.path.splitext(txt_path)[0] + ".done.txt"

    # cookie 转换：weibo.py 的 cookie.txt 是字符串格式，yt-dlp 需要 Netscape 格式
    original_cookie_arg = args.cookies
    cookie_path = prepare_cookie_file(args.cookies)
    cookie_converted = cookie_path is not None and cookie_path != original_cookie_arg

    entries = load_entries(txt_path)
    if not entries:
        print(f"[完成] {txt_path} 中没有待下载条目")
        cleanup_cookie_file(cookie_path, cookie_converted)
        return

    if args.limit > 0:
        entries = entries[: args.limit]

    print("=" * 70)
    print(f"待下载: {len(entries)} 条")
    print(f"txt:    {txt_path}")
    print(f"输出到: {args.output_dir}")
    print(f"done:   {done_path}")
    if cookie_path:
        print(f"cookie: {cookie_path}")
    else:
        print("cookie: 无（公开视频可下载，需登录的可能失败）")
    if args.dry_run:
        print("模式:   DRY-RUN（不实际下载）")
    print("=" * 70)

    succeeded: List[Tuple[str, str, str, str, str, str]] = []
    try:
        for idx, entry in enumerate(entries, start=1):
            print(f"\n[{idx}/{len(entries)}]")
            # 传转换后的 cookie 路径给下载函数
            cookie_for_dl = cookie_path or ""
            ok = download_one(entry, args.output_dir, cookie_for_dl, args.dry_run)
            if ok and not args.dry_run:
                succeeded.append(entry)
    finally:
        cleanup_cookie_file(cookie_path, cookie_converted)

    if not args.dry_run:
        move_to_done(txt_path, done_path, succeeded)

    print("\n" + "=" * 70)
    if args.dry_run:
        print(f"DRY-RUN 结束，共 {len(entries)} 条")
    else:
        print(f"完成: 成功 {len(succeeded)}/{len(entries)}")
        if len(succeeded) < len(entries):
            print(f"失败 {len(entries) - len(succeeded)} 条，下次运行会重试")
    print("=" * 70)


if __name__ == "__main__":
    main()
