# AliRss 使用说明

## 功能

抓取页面，制成RSS，上传到github

## 特点

* 使用xpath获取页面信息
* 支持用户登录

## 使用方法
下载项目后，按以下格式建立文件夹

    ALIRSS
    ├─export    放置输出的rss文件
    ├─ini       放置抓取页面的定义文件
    └─src       程序

在ini文件夹中放置需要抓页面的定义文件，示例如下：

    [SITE]
    url=http://lsstudent.sysu.edu.cn/Home/Notice                # 需要抓取的网址
    title=生科院学生网通知                                      # RSS标题
    description=
    login = False                                               # 是否需要登录
    linkin = True                                               # 是否跟踪链接

    [RULE]
    item=//div[@class="articlelistdiv"]//a[@target="_blank"]    # RSS条目的xpath（只要能区分出不同条目就可以了）
    item_link=                                                  # RSS条目的链接的xpath （以item为当前节点开始查找）
    item_title=                                                 # RSS条目的标题的xpath （以item为当前节点开始查找）


    [LINKIN]
    content=//div[@class="detailTail"]                          # 跟踪链接得到的页面所需提取的内容


    [LOGIN]
    url = http://www.example.com/login
    user = username:your_username
    password = password:your_password
    form = //form[@id=XXX]

保存成.ini为扩展名的文件，运行程序后，会在export文件夹生成同名的xml文件。

