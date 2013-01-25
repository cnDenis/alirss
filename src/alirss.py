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
import datetime
import traceback
import ConfigParser
import argparse
import logging
import urlparse

import chardet
import requests
import PyRSS2Gen
import lxml
import lxml.html
import lxml.html.clean
from bs4 import BeautifulSoup


INI_PATH = ""
EXPORT_PATH = ""
CONFIG_FILE = ""
REPO_NAME = ""
MAX_CONTENT_LEN = 30000
FETCH_INTERVAL = 1800  # 抓取间隔
DEBUG_MODE = True


if DEBUG_MODE:
    LOG_LEVEL = logging.DEBUG
    DEBUG_PATH = "../debug"
else:
    LOG_LEVEL = logging.INFO

#Log设置
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s', level=LOG_LEVEL)
lgDebug = logging.debug
lgInfo = logging.info
lgWarning = logging.warning
lgError = logging.error
lgCritical = logging.critical

lgDebug("alirss started!")


class AliError(Exception):
    def __init__(self, *arg, **kw):
        Exception.__init__(self, *arg, **kw)
        exc_type, exc_value, exc_traceback = sys.exc_info()
        lgError('%s.  File "%s" Line %s in <%s>\n    %s',
                self.message, *(traceback.extract_tb(exc_traceback)[0]))


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
        self._real_url = None
        self.session = session
        self._charset = charset
        self.sub_data = sub_data
        self.method = method
        self._rawtext = None
        self._soup = None
        self._tree = None

    @property
    def rawtext(self):
        """返回页面的内容（bytes，未解码）"""
        if not self._rawtext:
            self.fetch()
        return self._rawtext

    @property
    def real_url(self):
        """返回页面的真实URL，可能是跳转之后的结果"""
        if not self._real_url:
            self.fetch()
        return self._real_url

    @property
    def charset(self):
        """返回页面的字符集，用chardet检测"""
        if not self._charset:
            self._charset = get_charset(self.rawtext)
            lgDebug("page charset: %s", self._charset)
        return self._charset

    @property
    def soup(self):
        """返回页面的beautifulsoup解析得到的soup"""
        if not self._soup:
            self._soup = BeautifulSoup(
                self.rawtext, from_encoding=self.charset)
        return self._soup

    @property
    def tree(self):
        """返回页面用lxml解析得到的etree"""
        if not self._tree:
            parser = lxml.etree.HTMLParser(encoding=self.charset,
                                           remove_blank_text=True)
            self._tree = lxml.html.fromstring(
                self.rawtext, parser=parser, base_url=self.real_url)
        return self._tree

    def fetch(self):
        """抓取页面"""
        if not self.session:
            self.session = requests.session()

        lgDebug("Fetching: %s", self.url)

        if self.method.upper() == "POST":
            req = self.session.post(self.url, data=self.sub_data)
            lgDebug("Post data: %s", self.sub_data)
        else:
            req = self.session.get(self.url, params=self.sub_data)

        self._rawtext = req.content
        self._real_url = req.url

    def xpath(self, xpath):
        """按xpath查找页面中的内容"""
        return self.tree.xpath(xpath)

    def get_by_rule(self, rule):
        return self.xpath(rule)

    def form_submit(self, form, data):
        """获取form的提交地址、提交方法、hidden内容，与data一起提交，返回提交后的页面"""
        lnform = self.get_by_rule(form)[0]
        sub_url = abslink(self.real_url, lnform.get("action"))  # 登录的URLsub
        sub_method = lnform.get("method", "GET")  # GET是form标签中method属性的默认值
        sub_data = data

        hiddens = lnform.xpath(".//input[@type='hidden']")  # 隐藏在form里，要提交的东西
        for hd in hiddens:
            sub_data[hd.get("name")] = hd.get("value", "")

        lgDebug("submit to %s", sub_url)
        lgDebug("submit data: %s", sub_data)

        np = Page(url=sub_url, session=self.session,
                  charset=self.charset, method=sub_method, sub_data=data)
        np.fetch()
        return np


class Tag(lxml.html.HtmlElement):
    def get_by_rule(self, rule):
        return self.xpath(rule)


class Site(object):
    """一个频道的信息"""
    def __init__(self):
        self.url = ""
        self.urls = []
        self.real_url = ""  # 站点建立连接后的真实URL，有可能会是被重定向过的
        self.session = requests.session()  # 创建一个session，以keep-Alive，减少连接开销
        self.items = []
        self.old_items = set()
        self.linkin = False
        self.login = False
        self.xmlfile = ""
        self.pages = {}  # 装载一些进入过的页面
        self.cleaner = lxml.html.clean.Cleaner(scripts=False, style=False, links=False,
                                               javascript=False, comments=False, annoying_tags=False,
                                               meta=False, page_structure=False, frames=False,
                                               remove_unknown_tags=True, safe_attrs_only=True,
                                               remove_tags=["span"])
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

                    uf, un = login_user.split(":", 1)
                    pf, pw = login_pw.split(":", 1)
                    self.login_data = {uf: un, pf: pw}
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
            pg = Page(
                self.url, session=self.session, charset=self.site_charset)
            if DEBUG_MODE:
                with open(DEBUG_PATH + "/site.htm", "wb") as fp:
                    fp.write(pg.rawtext)

            self.parse_page(pg)

        if self.linkin:
            self.do_linkin_all()

    def do_login(self):
        """登录网页"""
        ln_page = Page(self.login_url, session=self.session)
        self.pages["login"] = ln_page.form_submit(
            form=self.login_form, data=self.login_data)

        if DEBUG_MODE:
            with open(DEBUG_PATH + "/login.htm", "wb") as fp:
                fp.write(ln_page.rawtext)
            with open(DEBUG_PATH + "/login_done.htm", "wb") as fp:
                fp.write(self.pages["login"].rawtext)
#TODO: 本地密码加密

    def parse_page(self, page):
        """解析一个页面，产生条目信息，装入self.items"""
        self.real_url = page.real_url
        self.charset = page.charset
        items = page.get_by_rule(self.rule_item)

        if DEBUG_MODE:
            with open(DEBUG_PATH + "/group.soup", "wb") as fp:
                for gp in items:
                    fp.write(lxml.etree.tostring(gp, encoding="utf-8"))

        for i in items:
            it = self.parse_item(i)
            self.items.append(it)

    def parse_item(self, tag):
        """解析一个条目，获取名字和链接"""
        lgDebug("tag is %s", tag)
        lgDebug("tag is %s", lxml.etree.tostring(tag, encoding="utf-8"))
        it = Item()
        if self.rule_item_title:
            tsoup = tag.xpath(self.rule_item_title)
            if isinstance(tsoup, list):
                tsoup = tsoup[0]
        else:
            tsoup = tag
        lgDebug("tsoup is %s", tsoup)

        if self.rule_item_link:
            lsoup = tag.xpath(self.rule_item_link)
            if isinstance(lsoup, list):
                lsoup = lsoup[0]
        else:
            lsoup = tag
        lgDebug("lsoup is %s", lsoup)

        try:
            it.title = u"".join(tsoup.itertext())
        except Exception as err:  # 如果it.title是字符串，则会报AttributeError
            lgDebug("text_content exception: %s", err)
            it.title = unicode(tsoup)
        lgDebug("item title: %s", it.title)

        try:
            link = lsoup.get("href")
        except Exception:  # 如果it.title是字符串，则会报TypeError
            link = unicode(lsoup)
        it.link = abslink(self.real_url, link)
        lgDebug("item link: %s", it.link)
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
                pg = Page(url=it.link,
                          session=self.session, charset=self.linkin_charset)
                lkcontent = pg.get_by_rule(self.linkin_content)
                cdata = u"".join([lxml.etree.tostring(
                    t, encoding=unicode) for t in lkcontent])
                cdata = self.cleaner.clean_html(cdata)
                cdata = cdata.replace("\r", "").replace("\n", " ")
                cdata.replace("]]>", ">")
                if len(cdata) > MAX_CONTENT_LEN:
                    if "<" in cdata:
                        cdata = u"".join(re.findall(r"<.*>", cdata[:MAX_CONTENT_LEN]))
                    else:
                        cdata = cdata[:MAX_CONTENT_LEN]
                    cdata = cdata + u"<a href='%s'>...阅读全文</a>" % it.link
                it.content = u"<![CDATA[%s]]>" % cdata
            except requests.exceptions.RequestException as err:  # 网页中坏链接是常有的事，在这里就处理掉
                lgWarning("requests error: %s", err)
                lgWarning("Error while following link %s.", it.link)
            except Exception as err:
                lgWarning("Linkin error: %s\n %s", err, sys.exc_info()[:2])
                lgWarning("Error while following link %s.", it.link)

    def write_xml(self, xmlfile=None):
        """输出RSS格式的xml文件"""
        site_info = dict(
            title=self.title,
            link=self.url,
            description=self.desc,
            pubDate=datetime.datetime.now()
        )

        rss_items = []
        for it in self.items:
            rss_it = PyRSS2Gen.RSSItem(title=it.title, link=it.link,
                                       guid=PyRSS2Gen.Guid(it.link),
                                       description=it.content)
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
        lgDebug("Reading old xml file: %s", self.xmlfile)
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


def get_charset(text):
    """返回网页中的字符集"""
    detector = chardet.detect(text)

    lgDebug("Detected encoding: %s with confidence %f", detector[
            "encoding"], detector["confidence"])
    if detector["encoding"].lower().startswith("gb"):
        return("gbk")
    else:
        return detector["encoding"]


def abslink(ref_url, link):
    """从网页中的路径生成URL，可以接受相对路径或绝对路径"""
    if "://" in link:  # 判断是否绝对路径
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
        ini.set("RULE", "item", "//p/a")
        ini.set("RULE", "item_link", "")
        ini.set("RULE", "item_title", "")

        ini.add_section("LINKIN")
        ini.set("LINKIN", "content", '//div[@id="main_right"]')
        ini.set("LINKIN", "charset", "")

        ini.add_section("LOGIN")
        ini.set("LOGIN", "url", "http://www.example.com/login")
        ini.set("LOGIN", "user", "username:your_username")
        ini.set("LOGIN", "password", "password:your_password")
        ini.set("LOGIN", "form", "//form[@id=XXX]")

        with io.open(example_file, "wb") as fp:
            ini.write(fp)


def read_config(conf_file=None):
    """读取程序的全局配置文件"""
    global ROOT_PATH
    global INI_PATH
    global EXPORT_PATH
    global CONFIG_FILE
    global FETCH_INTERVAL
    global REPO_NAME
    ROOT_PATH = os.path.split(os.path.realpath(__file__))[0]

    if not conf_file:
        CONFIG_FILE = "alirss.conf"
    else:
        CONFIG_FILE = conf_file

    if not os.path.isfile(CONFIG_FILE):
        lgInfo("CONFIG_FILE not exists: %s", CONFIG_FILE)
        default_config()

    try:
        config = ConfigParser.RawConfigParser()
        config.read(CONFIG_FILE)

        lgDebug("Read global config file %s", CONFIG_FILE)

        INI_PATH = config.get("PATH", "ini_path")
        EXPORT_PATH = config.get("PATH", "export_path")
        FETCH_INTERVAL = config.getint("FETCH", "interval")
        try:
            if config.getboolean("PUBLICATION", "public"):
                REPO_NAME = config.get("PUBLICATION", "reponame")
        except Exception:
            pass

    except Exception:
        ch = raw_input("Cannot read %s, generate default?" % CONFIG_FILE)
        if ch.lower().startswith("y"):
            default_config()
            print("Default config file, please restart program")


def print_config():

    conf = u"""\n
************************************************
    CONFIG_FILE =       {cff}
    INI_PATH =          {ini}
    EXPORT_PATH =       {exp}
    FETCH_INTERVAL =    {fet}
    REPO_NAME =         {isp}
************************************************
    """.format(cff=CONFIG_FILE, ini=INI_PATH, exp=EXPORT_PATH, fet=FETCH_INTERVAL,
               isp=REPO_NAME).encode("gbk")
    lgInfo(conf)


def default_config():
    """生成默认全局配置文件"""
    global CONFIG_FILE
    config = ConfigParser.RawConfigParser()
    config.add_section("PATH")
    config.set("PATH", "ini_path", "../ini")
    config.set("PATH", "export_path", "../export")

    config.add_section("FETCH")
    config.set("FETCH", "interval", 1800)

    config.add_section("PUBLICATION")
    config.set("PUBLICATION", "public", False)
    config.set("PUBLICATION", "reponame", "")
#    config.set("PUBLICATION", "username", "")
#    config.set("PUBLICATION", "password", "")

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
    except Exception as err:
        lgError(err)
    finally:
        site.exit()


def fetch_all_site():
    """遍历INI_PATH，抓取其中所有站点"""
    for fn in glob.glob("%s/*.ini" % INI_PATH):
        if os.path.split(fn)[-1].startswith("!"):
            continue
        else:
            fetch_site(fn)


def public():
    cwd = os.getcwd()
    os.chdir(EXPORT_PATH)
    lgInfo("pushing to %s", REPO_NAME)

    os.system("git add .")
    os.system('git commit -a -m "upload by alirss at %s"' % time.asctime())
    os.system("git push -u %s" % REPO_NAME)

    os.chdir(cwd)


def main():
    """程序入口"""
    argp = argparse.ArgumentParser(description="A local Page to RSS generator")
    argp.add_argument(
        "-t", "--test", nargs="?", const="*", help="test site(s)")
    argp.add_argument("--conf", nargs=1, help="specify a global config file")
    args = argp.parse_args()
    lgDebug("Arguments: %s", args)

    try:
        conf = args.conf[0]
        lgDebug("conf = %s", conf)
    except Exception:
        conf = None

    read_config(conf)
    default_ini()
    print_config()

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
            if REPO_NAME:
                public()
            lgInfo("Fetch done, wait %ss", FETCH_INTERVAL)
            time.sleep(FETCH_INTERVAL)

if __name__ == '__main__':
    main()
