#! /usr/bin/env python
#coding=utf-8
# by cnDenis <cndenis@gmail.com>

from __future__ import print_function
from __future__ import division

import os
import io
import glob
import time
import datetime
import ConfigParser
import argparse
import logging
import urlparse
import requests
import PyRSS2Gen
from bs4 import BeautifulSoup
from bs4 import SoupStrainer

ROOT_PATH = ""
INI_PATH = ""
EXPORT_PATH = ""
CONFIG_FILE = ""
FETCH_INTERVAL = 1800 #抓取间隔
LOG_LEVEL = logging.DEBUG

#Log设置
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=LOG_LEVEL)
lgDebug = logging.debug
lgInfo = logging.info
lgWarning = logging.warning
lgError = logging.error
lgCritical = logging.critical

class item():
    """RSS频道中的一个条目所的内容"""
    def __init__(self):
        self.title = ""
        self.desc = ""
        self.link = ""
        self.content = ""


class Site():
    """一个频道的信息"""
    def __init__(self, ini_file=None):
        self.url = ""
        self.real_url = "" #站点建立连接后的真实URL，有可能会是被重定向过的
        self.session = requests.session() #创建一个session，以keep-Alive，减少连接开销
        self.items = []
        self.ini_file = ini_file

    def read_ini(self, ini_file):
        """读取一个站点的抓取设置的ini文件"""
        self.ini_file = ini_file
        lgDebug("Reading ini file: %s", ini_file)
        ini = ConfigParser.RawConfigParser()
        ini.readfp(io.open(ini_file, encoding="utf-8"))
        self.url = ini.get("SITE", "url")
        self.title = ini.get("SITE", "title")
        self.desc = ini.get("SITE", "description")
        if not self.desc:
            self.desc = self.title

        self.rule_group = ini.get("RULE", "group")
        self.rule_item = ini.get("RULE", "item")
        self.rule_item_title = ini.get("RULE", "item_title")
        self.rule_item_link = ini.get("RULE", "item_link")

        if ini.has_option("LINKIN", "filter"):
            self.linkin_filter = ini.get("LINKIN", "filter")
        else:
            self.linkin_filter = None

        self.xmlfile = os.path.split(ini_file)[-1].rsplit(".", 1)[0] + ".xml"

    def parse_rule(self, rule):
        """解析ini文件中的规则"""
        lgDebug("parsing rule %s", rule)
        for rul in rule.split("|"):
            if rul[-1] and rul[-1].isdigit():
                ru, index = rul.rsplit(">", 1)
                ru = ru + ">"
                index = int(index)
            else:
                ru = rul
                index = 0

            r = BeautifulSoup(ru, "html.parser")
            lgDebug("parsing subrule %s to %s", ru, r)
            name = r.contents[0].name
            kw = r.contents[0].attrs
            yield name, kw, index

    def filter(self, soup, rule):
        """根据规测rule来过滤soup"""
        for name, kw, index in self.parse_rule(rule):
            soup = soup(name, **kw)[index]
        return soup


    def fetch(self):
        self.read_ini(self.ini_file)
        res = self.session.get(self.url)

        self.real_url = res.url
        text = res.text
        soup = BeautifulSoup(text)
        self.parse_group(soup)


    def parse_group(self, soup):
        """解析一个页面，产生条目信息，装入self.item"""
        group = self.filter(soup, self.rule_group)

        for iname, ikw, iindex in self.parse_rule(self.rule_item):
            break

        items = group(iname, **ikw)
        for i in items:
            it = self.parse_item(i)
            self.items.append(it)

    def parse_item(self, soup):
        """解析一个条目"""
        it = item()
        if self.rule_item_title:
            tsoup = self.filter(soup, self.rule_item_title)
        else:
            tsoup = soup

        if self.rule_item_link:
            lsoup = self.filter(soup, self.rule_item_link)
        else:
            lsoup = soup

        it.title = tsoup.text
        lgDebug("item title: %s" , it.title)

        link = lsoup["href"]
        if "://" in link:  #判断是否绝对路径
            it.link = link
        elif link.startswith("/"):
            urlp = urlparse.urlparse(self.real_url)
            it.link = urlp.scheme + "://" + urlp.netloc + link
        else:
            it.link = self.real_url.rsplit("/", 1)[0] + "/" + link

        lgDebug("item link: %s" , it.link)

        if self.linkin_filter:
            lgDebug("Following link: %s", it.link)

            lkreq = self.session.get(it.link)
            lksoup = BeautifulSoup(lkreq.text)
            lkcontent = self.filter(lksoup, self.linkin_filter)
            it.content = unicode(lkcontent)

        return it


    def write_xml(self, xmlfile=None):
        """输出RSS格式的xml文件"""
        site_info = dict(
                title = self.title,
                link = self.url,
                description = self.desc,
                pubDate = datetime.datetime.now()
                )

        rss_items = []
        for it in self.items:
            rss_it = PyRSS2Gen.RSSItem(title=it.title, link=it.link, \
                    guid=PyRSS2Gen.Guid(it.link), description=it.content)
            rss_items.append(rss_it)

        rss = PyRSS2Gen.RSS2(items=rss_items, **site_info)

        if xmlfile:
            xml_filename = xmlfile
        else:
            xml_filename = os.path.join(EXPORT_PATH, self.xmlfile)

        with open(xml_filename, "w") as fp:
            lgDebug("Writing xml file: %s", xml_filename)
            rss.write_xml(fp)



def default_ini():
    """生成配置文件的样本"""
    example_file = os.path.join(INI_PATH, "!example.ini")
    if not os.path.isfile(example_file):
        ini = ConfigParser.RawConfigParser()
        ini.add_section("SITE")
        ini.set("SITE", "url", "http://www.example.com")
        ini.set("SITE", "title", u"频道的标题".encode("utf8"))
        ini.set("SITE", "description", u"频道的描述".encode("utf8"))

        ini.add_section("RULE")
        ini.set("RULE", "group", "<div>|<p>1")
        ini.set("RULE", "item", "<a>")
        ini.set("RULE", "item_link", "")
        ini.set("RULE", "item_title", "")

        ini.add_section("LINKIN")
        ini.set("LINKIN", "filter", '<div id="main_right">')

        with io.open(example_file, "wb") as fp:
            ini.write(fp)


def read_config(conf_file=None):
    """读取程序的全局配置文件"""
    global ROOT_PATH
    global INI_PATH
    global EXPORT_PATH
    global CONFIG_FILE
    global FETCH_INTERVAL
    ROOT_PATH = os.path.split(os.path.realpath(__file__))[0]

    if not conf_file:
        CONFIG_FILE = "alirss.conf"

    if not os.path.isfile(CONFIG_FILE):
        defautl_config()

    try:
        config = ConfigParser.RawConfigParser()
        config.read(CONFIG_FILE)

        lgDebug("Read global config file %s", CONFIG_FILE)

        INI_PATH = config.get("PATH", "ini_path")
        EXPORT_PATH = config.get("PATH", "export_path")
        FETCH_INTERVAL = config.getint("FETCH", "interval")
    except:
        ch = raw_input("Cannot read %s, generate default?" % CONFIG_FILE)
        if ch.lower().startswith("y"):
            defautl_config()
            print("Default config file, please restart program")


def defautl_config():
    """生成默认全局配置文件"""
    global CONFIG_FILE
    config = ConfigParser.RawConfigParser()
    config.add_section("PATH")
    config.set("PATH", "ini_path", "../ini")
    config.set("PATH", "export_path", "../export")

    if not CONFIG_FILE:
        CONFIG_FILE = "alirss.conf"

    with io.open(CONFIG_FILE, "wb") as fp:
        lgInfo("Writing global config file, %s", CONFIG_FILE)
        config.write(fp)

def fetch_site(ini_file):
    """读入ini文件，并抓取指定站点，输出xml文件"""
    fn = ini_file
    if not fn.endswith(".ini"):
        fn = fn + ".ini"

    if not os.path.isfile(fn):
        fn = os.path.join(INI_PATH, fn)

    if not os.path.isfile(fn):
        lgError("ini file not found: %s", ini_file)
        return

    try:
        site = Site(fn)
        site.fetch()
        site.write_xml()
    except ConfigParser.Error as err:
        lgError(err)

def fetch_all_site():
    """遍历INI_PATH，抓取其中所有站点"""
    for fn in glob.glob("%s/*.ini" % INI_PATH):
        if os.path.split(fn)[-1].startswith("!"):
            continue
        else:
            fetch_site(fn)

def main():
    """程序入口"""
    argp = argparse.ArgumentParser(description="A local Page to RSS generator")
    argp.add_argument("-t", "--test", nargs="?", const="*", help="test site(s)")
    argp.add_argument("--conf", nargs=1, help="specify a global config file")
    args = argp.parse_args()
    lgDebug("Arguments: %s", args)

    read_config(args.conf)
    default_ini()

    if args.test:
        lgInfo("Running test: %s", args.test)
        if args.test == "*":
            fetch_all_site()
        else:
            fn = args.test
            fetch_site(fn)
    else:
        while True:
            lgInfo("Start fretch all site")
            fetch_all_site()
            lgInfo("Fetch done, wait %ss", FETCH_INTERVAL)
            time.sleep(FETCH_INTERVAL)

if __name__ == '__main__':
    main()
