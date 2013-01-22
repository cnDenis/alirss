#! /usr/bin/env python
#coding=utf-8
# by cnDenis <cndenis@gmail.com>

from __future__ import print_function
from __future__ import division

import os
import io
import re
import sys
import glob
import time
import types
import datetime
import ConfigParser
import argparse
import logging
import urlparse
import StringIO
import chardet
import requests
import PyRSS2Gen
from bs4 import BeautifulSoup

import traceback

ROOT_PATH = ""
INI_PATH = ""
EXPORT_PATH = ""
CONFIG_FILE = ""
FETCH_INTERVAL = 1800 #抓取间隔
DEBUG_MODE = True

if DEBUG_MODE:
    LOG_LEVEL = logging.DEBUG
    DEBUG_PATH = os.path.join(ROOT_PATH, "../debug")
else:
    LOG_LEVEL = logging.INFO

#Log设置
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=LOG_LEVEL)
lgDebug = logging.debug
lgInfo = logging.info
lgWarning = logging.warning
lgError = logging.error
lgCritical = logging.critical

class AliError(Exception):
    def __init__(self, *arg, **kw):
        Exception.__init__(self, *arg, **kw)
        exc_type, exc_value, exc_traceback = sys.exc_info()
        lgError('%s.  File "%s" Line %s in <%s>\n    %s', self.message, *(traceback.extract_tb(exc_traceback)[0]))

class RuleError(AliError):
    pass

class RuleParseError(RuleError):
    pass

class RuleFilterError(RuleError):
    pass

class Item(object):
    """RSS频道中的一个条目所的内容"""
    def __init__(self):
        self.title = ""
        self.desc = ""
        self.link = ""
        self.content = ""

class Page(object):
    """抓取回来的一个页面"""
    def __init__(self, url, session=None, charset=None, method="GET", sub_data=None):
        self.url = url
        self.real_url = ""
        self.session = session
        self.charset = charset
        self.sub_data = sub_data
        self.method = method
        self.rawtext = ""
        self.soup = None
        self.next_page = None

    def fetch(self):
        if not self.session:
            self.session = requests.session()

        lgDebug("Fetching: %s", self.url)

        if self.method.upper() == "POST":
            req = self.session.post(self.url, data=self.sub_data)
            lgDebug("Post data: %s", self.sub_data)
        else:
            req = self.session.get(self.url, params=self.sub_data)

        self.rawtext = req.content
        self.real_url = req.url
        if not self.charset:
            charset = chardet.detect(self.rawtext)
        else:
            charset = self.charset
        self.soup = BeautifulSoup(self.rawtext)

    def linkin(self, rule):
        lnsoup = rule_filter(self.soup, rule)
        try:
            link = lnsoup["href"]
        except KeyError:
            link = lnsoup
        link = abslink(self.real_url, link)

        lgDebug("Folling link: %s", link)

        np = Page(url=link, session=self.session, charset=self.charset)
        np.fetch()
        self.next_page = np

    def form_submit(self, form, data):
        lnform = rule_filter(self.soup, form)
        sub_url = abslink(self.real_url, lnform["action"]) #登录的URLsub
        try:
            sub_method = lnform["method"]
        except KeyError:
            sub_method = "GET" # GET是form标签中method属性的默认值

        sub_data = data

        hiddens = lnform("input", type="hidden") #隐藏在form里，要提交的东西
        for hd in hiddens:
            sub_data[hd["name"]] = hd["value"]

        lgDebug("submit to %s", sub_url)
        lgDebug("submit data: %s", sub_data)

        np = Page(url=sub_url, session=self.session, charset=self.charset, method=sub_method, sub_data=data)
        np.fetch()
        self.next_page = np


class Site(object):
    """一个频道的信息"""
    def __init__(self):
        self.url = ""
        self.urls = []
        self.real_url = "" #站点建立连接后的真实URL，有可能会是被重定向过的
        self.session = requests.session() #创建一个session，以keep-Alive，减少连接开销
        self.items = []
        self.old_items = set()
        self.linkin = False
        self.login = False
        self.xmlfile = ""
        self.pages = {} #装载一些进入过的页面
#TODO: 对网页大小的限制
#TODO: 对资源使用的限制

    def read_ini(self, ini_file=None):
        """读取一个站点的抓取设置的ini文件"""
        if ini_file:
            self.ini_file = ini_file
        lgDebug("Reading ini file: %s", ini_file)
        ini = ConfigParser.RawConfigParser()
        ini.readfp(io.open(ini_file, encoding="utf-8"))
        try:
            #读[SITE]段
            urls = ini.get("SITE", "url")
            self.urls = urls.split("|")
            self.title = ini.get("SITE", "title")
            try:
                self.desc = ini.get("SITE", "description")
            except ConfigParser.NoOptionError:
                self.desc = self.title

            try:
                self.site_charset = ini.get("SITE", "charset")
            except ConfigParser.NoOptionError:
                self.site_charset = None

            try:
                self.linkin = ini.getboolean("SITE", "linkin")
            except ConfigParser.NoOptionError:
                self.linkin = False

            try:
                self.login = ini.getboolean("SITE", "login")
            except ConfigParser.NoOptionError:
                self.login = False

            #读[RULE]段
            self.rule_group = ini.get("RULE", "group")
            self.rule_item = ini.get("RULE", "item")
            self.rule_item_title = ini.get("RULE", "item_title")
            self.rule_item_link = ini.get("RULE", "item_link")

            #读[LINKIN]段
            if self.linkin:
                if ini.has_section("LINKIN"):
                    try:
                        self.linkin_content = ini.get("LINKIN", "content")
                    except ConfigParser.NoOptionError:
                        self.linkin_filter = "<body>"

                    try:
                        self.linkin_charset = ini.get("LINKIN", "charset")
                    except ConfigParser.NoOptionError:
                        self.linkin_charset = None
                else:
                    lgWarning("linkin is True but no [LINKIN] session provide. Cannot follow link in items")
                    self.linkin = False

            #读[LOGIN]段
            if self.login:
                if ini.has_section("LOGIN"):
                    self.login_url = ini.get("LOGIN", "url")
                    self.login_form = ini.get("LOGIN", "form")
                    login_user = ini.get("LOGIN", "user")
                    login_pw = ini.get("LOGIN", "password")

                    uf, un = login_user.split(":",1)
                    pf, pw = login_pw.split(":",1)
                    self.login_data = {uf:un, pf:pw}
                else:
                    lgWarning("login is set to True but no [LOGIN] session provide. Cannot login")
                    self.login = False

        except ConfigParser.NoOptionError as err:
            lgError("ini file error, %s", err)
            raise err

#TODO:linkn的设定
#TODO:user_agent支持
        xmlfile = os.path.split(ini_file)[-1].rsplit(".", 1)[0] + ".xml"
        self.xmlfile = os.path.join(EXPORT_PATH, xmlfile)


    def fetch(self):
        """抓取站点"""
        if self.login:
            self.do_login()

        self.get_old_items()
        for self.url in self.urls:
            res = self.session.get(self.url)

            self.real_url = res.url
            text = res.content
            if self.site_charset:
                charset = self.site_charset
            else:
                charset = get_charset(text)
            lgDebug("Using page charset: %s", charset)

            soup = BeautifulSoup(text, from_encoding=charset)
            if DEBUG_MODE:
                with open(DEBUG_PATH + "/site.htm", "wb") as fp:
                    fp.write(soup.prettify("utf-8"))

            self.parse_group(soup)

        if self.linkin:
            self.do_linkin_all()


    def do_login(self):
        """登录网页"""
        ln_page = Page(self.login_url, session=self.session)
        ln_page.fetch()
        ln_page.form_submit(form=self.login_form, data=self.login_data)
        self.pages["login"] = ln_page.next_page
        if DEBUG_MODE:
            with open(DEBUG_PATH + "/login.htm", "wb") as fp:
                fp.write(ln_page.rawtext)
            with open(DEBUG_PATH + "/login_done.htm", "wb") as fp:
                fp.write(ln_page.next_page.rawtext)
#TODO: 本地密码加密


    def parse_group(self, soup):
        """解析一个页面，产生条目信息，装入self.items"""
        group = rule_filter(soup, self.rule_group)

        if DEBUG_MODE:
            with open(DEBUG_PATH + "/group.soup", "wb") as fp:
                fp.write(group.prettify("utf-8"))

        iname, ikw, iindex, field = rule_parse(self.rule_item).next()

        itemsoups = group(iname, **ikw)
        for i in itemsoups:
            it = self.parse_item(i)
            self.items.append(it)


    def parse_item(self, soup):
        """解析一个条目，获取名字和链接"""
        it = Item()
        if self.rule_item_title:
            tsoup = rule_filter(soup, self.rule_item_title)
        else:
            tsoup = soup

        if self.rule_item_link:
            lsoup = rule_filter(soup, self.rule_item_link)
        else:
            lsoup = soup

        try:
            it.title = tsoup.text
        except AttributeError: #如果it.title是字符串，则会报AttributeError
            it.title = tsoup
        lgDebug("item title: %s" , it.title)

        try:
            link = lsoup["href"]
        except TypeError: #如果it.title是字符串，则会报TypeError
            link = unicode(lsoup)
        it.link = abslink(self.real_url, link)
        lgDebug("item link: %s" , it.link)
        return it


    def do_linkin_all(self, refresh=False):
        for it in self.items:
            self.do_linkin(it, refresh)

    def do_linkin(self, it, refresh=False):
        guid = unicode(it.link)
        if not refresh and guid in self.old_items:
            lgDebug("Item exist, not follow: %s", guid)
            it.content = self.old_items[guid]
        else:
            try:
                lgDebug("Following new item link: %s", it.link)
                pg = Page(url=it.link, session=self.session, charset=self.linkin_charset)
                pg.fetch()
                lksoup = pg.soup
                lkcontent = rule_filter(lksoup, self.linkin_content)
                it.content = unicode(lkcontent)
            except requests.exceptions.RequestException as err: #网页中坏链接是常有的事，在这里就处理掉
                lgWarning("requests error: %s", err)
                lgWarning("Error while following link %s.", it.link)
            except Exception as err:
                lgWarning("Linkin error: %s\n %s", err, sys.exc_info()[:2])
                lgWarning("Error while following link %s.", it.link)

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
            xml_filename = self.xmlfile

        with open(xml_filename, "w") as fp:
            lgDebug("Writing xml file: %s", xml_filename)
            rss.write_xml(fp, encoding="utf-8")

    def get_old_items(self):
        lgDebug("Reading old xml file: %s" , self.xmlfile)
        self.old_items = {}
        try:
            with io.open(self.xmlfile, "rb") as fp:
                xsoup = BeautifulSoup(fp.read(), "lxml")
                for it in xsoup("item"):
                    guid = unicode(it.find("guid").text)
                    content = unicode(it.find("description").text)
                    self.old_items[guid] = content
        except IOError as err:
            lgInfo("Read old xml file %s Error: %s", self.xmlfile, err)

    def exit(self):
        self.session.__exit__()


def rule_parse(rule):
    """解析ini文件中的规则"""
    lgDebug("parsing rule %s", rule)
    for rul in rule.split("|"):
        try:
            rul_ori = rul
            rul = rul.strip()
            if ">:" in rul: # :XX代表取属性，即soup[XX]
                rul, field = rul.rsplit(":", 1)
                field = ":" + field
            elif ">." in rul: # .XXX表示取soup.XXX
                rul, field = rul.rsplit(".", 1)
                field = "." + field
            else:
                field = ""

            if rul.endswith("*"): # *表示合并所有查找到的项
                rul = rul.strip("*")
                index = "*"
            elif rul[-1] and rul[-1].isdigit(): # 数字表示取指定一项或几项
                rul, index = rul.rsplit(">", 1)
                rul = rul + ">"
                indexs = []
                for ind in index.split(","):
                    if "-" in ind:
                        i1, i2 = ind.split("-", 1)
                        i1 = int(i1)
                        i2 = int(i2)+1
                        indexs.extend(xrange(i1, i2))
                    else:
                        indexs.append(int(ind))
                index = indexs
            else:
                index = 0

            r = BeautifulSoup(rul, "html.parser")
            name = r.contents[0].name
            kw = r.contents[0].attrs
            lgDebug("parsing subrule %s to %s, yield (%s, %s, %s, %s)", rul, r, name, kw, index, field)
            yield name, kw, index, field
        except LookupError as err:
            lgError("Rule parse error on %s :%s", rul_ori, err)
            raise RuleParseError(err)

def rule_filter(soup, rule):
    """根据规测rule来过滤soup，获取指定的HTML元素或属性"""
    try:
        for name, kw, index, field in rule_parse(rule):
            if index == "*":
                st = BeautifulSoup("", "html.parser")
                for s in soup(name, **kw):
                    st.append(s)
                soup = st
            elif isinstance(index, types.ListType):
                st = BeautifulSoup("", "html.parser")
                sp = soup(name, **kw)
                for i in index:
                    st.append(sp[i])
                soup = st
            else:
                soup = soup(name, **kw)[index]

        if field.startswith(":"):
            f = field.strip(":")
            return soup[f]
        elif field.startswith("."):
            f = field.strip(".")
            return getattr(soup, f)
        else:
            return soup
    except RuleParseError as err:
        raise err
    except StandardError as err:
        lgError("Rule filter error, %s", err)
        raise RuleFilterError(err)


def get_charset(text):
    """返回网页中的字符集"""
    detector = chardet.detect(text)

    lgDebug("Detected encoding: %s with confidence %f", detector["encoding"], detector["confidence"])
    return detector["encoding"]


def abslink(ref_url, link):
    """从网页中的路径生成URL，可以接受相对路径或绝对路径"""
    if "://" in link:  #判断是否绝对路径
        abslink = link
    elif link.startswith("/"):
        urlp = urlparse.urlparse(ref_url)
        abslink = urlp.scheme + "://" + urlp.netloc + link
    else:
        abslink = ref_url.rsplit("/", 1)[0] + "/" + link

    return abslink


def default_ini():
    """生成配置文件的样本"""
    example_file = os.path.join(INI_PATH, "!example.ini")
    if not os.path.isfile(example_file):
        ini = ConfigParser.RawConfigParser()
        ini.add_section("SITE")
        ini.set("SITE", "url", "http://www.example.com")
        ini.set("SITE", "title", u"频道的标题".encode("utf8"))
        ini.set("SITE", "description", u"频道的描述".encode("utf8"))
        ini.set("SITE", "charset", "")
        ini.set("SITE", "login", False)
        ini.set("SITE", "linkin", True)

        ini.add_section("RULE")
        ini.set("RULE", "group", "<div>|<p>1")
        ini.set("RULE", "item", "<a>")
        ini.set("RULE", "item_link", "")
        ini.set("RULE", "item_title", "")

        ini.add_section("LINKIN")
        ini.set("LINKIN", "content", '<div id="main_right">')
        ini.set("LINKIN", "charset", "")

        ini.add_section("LOGIN")
        ini.set("LOGIN", "url", "http://www.example.com/login")
        ini.set("LOGIN", "user", "username:your_username")
        ini.set("LOGIN", "password", "password:your_password")
        ini.set("LOGIN", "form", "<form id=XXX>")

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

    config.add_section("FETCH")
    config.set("FETCH", "interval", 1800)

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
        site = Site()
        site.read_ini(fn)
        site.fetch()
        site.write_xml()
    except ConfigParser.Error as err:
        lgError("ConfigParser Error, please check your ini file")
    except requests.exceptions.RequestException as err:
        lgError("Network Error")
        lgError(err, sys.exc_info()[:2])
    finally:
        site.exit()

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
