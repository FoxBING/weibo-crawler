#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
按微博 ID 列表批量爬取脚本。

从 weibo_list.txt 读取微博 ID（每行一个），完全调用 weibo.py 的 Weibo 类
进行解析、下载和输出。同一用户的微博会自动分组批量处理，效率更高。

用法：
    python crawl_weibo_list.py                  # 默认读 weibo_list.txt
    python crawl_weibo_list.py 另一个列表.txt   # 指定列表文件
"""

import json
import logging
import logging.config
import os
import random
import sys
import warnings
from collections import OrderedDict, defaultdict
from datetime import datetime
from time import sleep

warnings.filterwarnings("ignore")

if not os.path.isdir("log/"):
    os.makedirs("log/")
logging_path = os.path.split(os.path.realpath(__file__))[0] + os.sep + "logging.conf"
logging.config.fileConfig(logging_path)
logger = logging.getLogger("weibo")

DTFORMAT = "%Y-%m-%dT%H:%M:%S"

import json5
from weibo import Weibo


def get_config() -> dict:
    """读取 config.json 配置（支持 JSON5 注释）"""
    config_path = os.path.split(os.path.realpath(__file__))[0] + os.sep + "config.json"
    if not os.path.isfile(config_path):
        logger.error("不存在配置文件 config.json")
        sys.exit()
    with open(config_path, encoding="utf-8") as f:
        try:
            return json5.loads(f.read())
        except Exception:
            return json.loads(f.read())


def read_weibo_list(path: str) -> list:
    """读取微博 ID 列表文件，跳过空行和 # 注释"""
    if not os.path.isfile(path):
        logger.error("不存在微博列表文件: %s", path)
        sys.exit()
    ids = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            wid = line.strip()
            if wid and not wid.startswith("#"):
                ids.append(wid)
    return ids


def fetch_weibo_detail(session, headers, weibo_id: str) -> dict:
    """获取单条微博详情 API 返回的 status 对象"""
    url = f"https://m.weibo.cn/detail/{weibo_id}"
    logger.info("获取微博详情: %s", url)
    for i in range(5):
        sleep(random.uniform(1.0, 2.5))
        try:
            html = session.get(url, headers=headers, verify=False, timeout=10).text
            html = html[html.find('"status":'):]
            html = html[:html.rfind('"call"')]
            html = html[:html.rfind(",")]
            html = "{" + html + "}"
            js = json.loads(html, strict=False)
            weibo_info = js.get("status")
            if weibo_info:
                return weibo_info
        except Exception as e:
            logger.error("第 %d 次获取失败: %s", i + 1, e)
            sleep(2 ** (i + 1))
    logger.error("获取微博详情失败: %s", weibo_id)
    return None


def setup_user_context(wb: Weibo, user_info: dict, config: dict) -> None:
    """根据 API 返回的 user 对象初始化 wb.user 和 wb.user_config"""
    wb.user = OrderedDict()
    wb.user["id"] = user_info.get("id", "")
    wb.user["screen_name"] = user_info.get("screen_name", "未知用户")
    wb.user["gender"] = user_info.get("gender", "")
    wb.user["statuses_count"] = 0
    wb.user["followers_count"] = 0
    wb.user["follow_count"] = 0
    wb.user["description"] = user_info.get("description", "")
    wb.user["profile_url"] = user_info.get("profile_url", "")
    wb.user["profile_image_url"] = user_info.get("profile_image_url", "")
    wb.user["avatar_hd"] = user_info.get("avatar_hd", "")
    wb.user["urank"] = user_info.get("urank", 0)
    wb.user["mbrank"] = user_info.get("mbrank", 0)
    wb.user["verified"] = user_info.get("verified", False)
    wb.user["verified_type"] = user_info.get("verified_type", -1)
    wb.user["verified_reason"] = user_info.get("verified_reason", "")
    for field in ["birthday", "location", "ip_location", "education",
                  "company", "registration_time", "sunshine"]:
        wb.user[field] = ""
    wb.user_config = {
        "user_id": str(wb.user["id"]),
        "since_date": config.get("since_date", "1900-01-01T00:00:00"),
        "end_date": "",
        "query_list": [],
    }


def parse_one_weibo(wb: Weibo, weibo_info: dict) -> dict:
    """解析一条微博（含长微博回退和转发处理），返回解析后的 weibo 对象"""
    weibo_id = str(weibo_info.get("id", ""))
    is_long = weibo_info.get("isLongText") or (weibo_info.get("pic_num", 0) > 9)
    if is_long:
        weibo = wb.get_long_weibo(weibo_id)
        if not weibo:
            weibo = wb.parse_weibo(weibo_info)
    else:
        weibo = wb.parse_weibo(weibo_info)

    weibo["created_at"], weibo["full_created_at"] = wb.standardize_date(
        weibo_info["created_at"]
    )
    weibo["edited"] = weibo_info.get("edit_count", 0) > 0
    weibo["edit_count"] = weibo_info.get("edit_count", 0)

    # 转发微博：获取原微博完整信息
    retweeted = weibo_info.get("retweeted_status")
    if retweeted and retweeted.get("id"):
        retweet_id = str(retweeted.get("id"))
        if retweeted.get("isLongText"):
            retweet = wb.get_long_weibo(retweet_id)
            if not retweet:
                retweet = wb.parse_weibo(retweeted)
        else:
            retweet = wb.parse_weibo(retweeted)
        retweet["created_at"], retweet["full_created_at"] = wb.standardize_date(
            retweeted["created_at"]
        )
        weibo["retweet"] = retweet

    return weibo


def main() -> None:
    """入口：读取列表 → 按用户分组 → 逐用户批量写入"""
    config = get_config()
    # user_id_list 对按微博 ID 爬取无意义，占位即可
    config["user_id_list"] = [0]

    list_path = sys.argv[1] if len(sys.argv) > 1 else "weibo_list.txt"
    weibo_ids = read_weibo_list(list_path)
    if not weibo_ids:
        logger.error("%s 中没有有效的微博 ID", list_path)
        return

    logger.info("=" * 60)
    logger.info("共 %d 条微博待处理，来源: %s", len(weibo_ids), list_path)
    logger.info("=" * 60)

    wb = Weibo(config)

    # 第一阶段：逐条获取详情，按用户分组
    # key = user_id, value = list of (weibo_id, weibo_info)
    grouped: dict = defaultdict(list)
    for idx, wid in enumerate(weibo_ids, start=1):
        logger.info("[%d/%d] 微博ID: %s", idx, len(weibo_ids), wid)
        weibo_info = fetch_weibo_detail(wb.session, wb.headers, wid)
        if not weibo_info:
            logger.warning("跳过: %s（获取失败）", wid)
            continue
        user_info = weibo_info.get("user")
        if not user_info:
            logger.warning("跳过: %s（无用户信息）", wid)
            continue
        user_id = str(user_info.get("id", wid))
        grouped[user_id].append((wid, weibo_info, user_info))

    if not grouped:
        logger.error("没有成功获取任何微博")
        return

    # 第二阶段：按用户批量解析 + 写入
    logger.info("=" * 60)
    logger.info("涉及 %d 个用户，开始批量处理", len(grouped))
    logger.info("=" * 60)

    total_ok = 0
    for user_id, items in grouped.items():
        # 每个用户重置 Weibo 实例状态
        wb.weibo = []
        wb.weibo_id_list = []
        wb.got_count = 0
        setup_user_context(wb, items[0][2], config)

        logger.info("-" * 40)
        logger.info("用户: %s (ID: %s)，%d 条微博",
                    wb.user["screen_name"], user_id, len(items))

        for wid, weibo_info, _ in items:
            try:
                weibo = parse_one_weibo(wb, weibo_info)
                wb.weibo.append(weibo)
                wb.weibo_id_list.append(weibo["id"])
                wb.got_count += 1
                total_ok += 1
            except Exception as e:
                logger.error("解析失败 %s: %s", wid, e)

        if wb.weibo:
            wb.write_data(0)
            logger.info("用户 %s 处理完毕: %d 条", wb.user["screen_name"], wb.got_count)

    logger.info("=" * 60)
    logger.info("全部完成: 成功 %d/%d，输出目录: %s",
                total_ok, len(weibo_ids), config.get("output_directory", "weibo_data"))
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
