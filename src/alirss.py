#! /usr/bin/env python
#coding=utf-8
# by cnDenis <cndenis@gmail.com>

from __future__ import print_function
from __future__ import division

import os
import io
import glob
import datetime
import ConfigParser
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
    def __init__(self):
        self.url = ""
        self.real_url = "" #站点建立连接后的真实URL，有可能会是被重定向过的
        self.session = requests.session() #创建一个session，以keep-Alive，减少连接开销
        self.items = []

    def read_ini(self, ini_file):
        """读取一个站点的抓取设置的ini文件"""
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
        self.rule_linkin_filter = ini.get("LINKIN", "filter")


    def parse_rule(self, rule):
        """解析ini文件中的规则"""
        for rul in rule.split("|"):
            if rul[-1] and rul[-1].isdigit():
                ru, index = rul.rsplit(">", 1)
                index = int(index)
            else:
                ru = rul
                index = 0

            r = BeautifulSoup(ru, "html.parser")
            name = r.contents[0].name
            kw = r.contents[0].attrs
            yield name, kw, index

    def filter(self, soup, rule):
        """根据规测rule来过滤soup"""
        for name, kw, index in self.parse_rule(rule):
            soup = soup(name, **kw)[index]
        return soup


    def fetch(self):
        try:
            res = self.session.get(self.url)
        except Exception as err:
            lgError(Exception)
            return

        self.real_url = res.url
        text = res.text
        soup = BeautifulSoup(text)
        self.parse_group(soup)


    def parse_group(self, soup):
        group = self.filter(soup, self.rule_group)

        for iname, ikw, iindex in self.parse_rule(self.rule_item):
            break

        items = group(iname, **ikw)
        for i in items:
            it = self.parse_item(i)
            self.items.append(it)

    def parse_item(self, soup):
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

        link = lsoup["href"]
        if "://" in link:  #判断是否绝对路径
            it.link = link
        elif link.startswith("/"):
            urlp = urlparse.urlparse(self.real_url)
            it.link = urlp.scheme + "://" + urlp.netloc + link
        else:
            it.link = self.real_url.rsplit("/", 1)[0] + "/" + link


        lgDebug("item title: %s" , it.title)
        lgDebug("item link: %s" , it.link)


        lkreq = self.session.get(it.link)
        lksoup = BeautifulSoup(lkreq.text)
        lkcontent = self.filter(lksoup, self.rule_linkin_filter)
        it.content = unicode(lkcontent)

        return it


    def write_xml(self):

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

        xml_filename = os.path.join(EXPORT_PATH, "lss.xml")
        with open(xml_filename, "w") as fp:
            rss.write_xml(fp)



def read_inis():
    """读取一个文件夹中的所有不以!开头的ini文件"""
    global INI_PATH
    for fn in glob.glob("%s/*.ini" % INI_PATH):
        if fn.startswith("!"):
            continue
        else:
            site = Site()
            site.read_ini(fn)
            site.fetch()
            site.write_xml()

def read_config():
    """读取程序的全局配置文件"""
    global ROOT_PATH
    global INI_PATH
    global EXPORT_PATH
    global CONFIG_FILE
    ROOT_PATH = os.path.split(os.path.realpath(__file__))[0]

    if not CONFIG_FILE:
        CONFIG_FILE = "alirss.conf"

    if not os.path.isfile(CONFIG_FILE):
        defautl_config()

    try:
        config = ConfigParser.RawConfigParser()
        config.read(CONFIG_FILE)
        INI_PATH = config.get("PATH", "ini_path")
        EXPORT_PATH = config.get("PATH", "export_path")
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

    with open(CONFIG_FILE, "wb") as fp:
        config.write(fp)

def main():
    read_config()
    read_inis()



if __name__ == '__main__':
    main()
