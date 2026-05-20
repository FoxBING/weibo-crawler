#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import logging
import logging.config
import os
import random
import sys
import warnings
from collections import OrderedDict
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
import requests
from requests.adapters import HTTPAdapter

from weibo import Weibo


def get_config():
    config_path = os.path.split(os.path.realpath(__file__))[0] + os.sep + "config.json"
    if not os.path.isfile(config_path):
        logger.warning("不存在配置文件config.json")
        sys.exit()
    try:
        with open(config_path, encoding="utf-8") as f:
            config_content = f.read()
            try:
                config = json5.loads(config_content)
            except Exception:
                config = json.loads(config_content)
            return config
    except Exception as e:
        logger.error(f"读取配置文件失败: {e}")
        sys.exit()


def fetch_weibo_detail(session, headers, weibo_id):
    url = f"https://m.weibo.cn/detail/{weibo_id}"
    logger.info(f"获取微博详情: {url}")

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
            logger.error(f"第 {i+1} 次获取失败: {e}")
            sleep(2 ** (i + 1))

    logger.error("获取微博详情失败")
    return None


def main():
    config = get_config()

    weibo_id = input("请输入微博ID: ").strip()
    if not weibo_id:
        logger.error("微博ID不能为空")
        return

    config["user_id_list"] = [0]
    config["output_directory"] = "test"
    config["write_mode"] = ["csv", "json", "markdown"]
    config["original_pic_download"] = 1
    config["retweet_pic_download"] = 1
    config["original_video_download"] = 1
    config["retweet_video_download"] = 1
    config["original_live_photo_download"] = 1
    config["retweet_live_photo_download"] = 1
    config["download_comment"] = 0
    config["download_repost"] = 0
    config["only_crawl_original"] = 0

    wb = Weibo(config)

    weibo_info = fetch_weibo_detail(wb.session, wb.headers, weibo_id)
    if not weibo_info:
        return

    user_info = weibo_info.get("user")
    if not user_info:
        logger.error("微博中没有用户信息")
        return

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

    logger.info(f"用户: {wb.user['screen_name']} (ID: {wb.user['id']})")

    is_long = weibo_info.get("isLongText") or (
        weibo_info.get("pic_num", 0) > 9
    )

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

    retweeted_status = weibo_info.get("retweeted_status")
    if retweeted_status and retweeted_status.get("id"):
        retweet_id = retweeted_status.get("id")
        is_long_retweet = retweeted_status.get("isLongText")
        if is_long_retweet:
            retweet = wb.get_long_weibo(retweet_id)
            if not retweet:
                retweet = wb.parse_weibo(retweeted_status)
        else:
            retweet = wb.parse_weibo(retweeted_status)
        retweet["created_at"], retweet["full_created_at"] = wb.standardize_date(
            retweeted_status["created_at"]
        )
        weibo["retweet"] = retweet

    wb.weibo.append(weibo)
    wb.weibo_id_list.append(weibo["id"])
    wb.got_count = 1

    logger.info("=" * 60)
    wb.print_weibo(weibo)
    logger.info("=" * 60)

    logger.info("开始写入数据并下载文件...")
    wb.write_data(0)

    logger.info("测试完成！输出目录: test/")


if __name__ == "__main__":
    main()
