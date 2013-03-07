# AliRss 使用说明

## 功能

抓取页面，生成RSS格式的xml文件，上传到github等远程仓库

## 特点

* 使用xpath获取页面信息
* 支持用户登录

## 依赖包

* requests
* chardet
* bs4
* lxml
* PyRSS2Gen

## 使用方法
下载项目后，按以下格式建立文件夹

    ALIRSS
    ├─export    放置输出的rss文件
    ├─ini       放置抓取页面的定义文件
    └─src       程序

在ini文件夹中放置需要抓页面的定义文件，示例如下：

    ##### 站点设置部分 #####
    [SITE]
    # 需要抓取的网址
    url=http://lsstudent.sysu.edu.cn/Home/Notice                

    # RSS标题
    title=生科院学生网通知                                      


    description=

    # 是否需要登录
    login = False                                               

    # 是否跟踪链接
    linkin = True                                               


    ##### 条目抓取规则部分 #####
    [RULE]
    # RSS条目的xpath（只要能区分出不同条目就可以了）
    item=//div[@class="articlelistdiv"]//a[@target="_blank"]    

    # RSS条目的链接的xpath （以item为当前节点开始查找）
    item_link=                                                  

    # RSS条目的标题的xpath （以item为当前节点开始查找）
    item_title=                                                 


    [LINKIN]
    # 跟踪链接得到的页面所需提取的内容
    content=//div[@class="detailTail"]                          


    [LOGIN]
    url = http://www.example.com/login
    user = username:your_username
    password = password:your_password
    form = //form[@id=XXX]

保存成.ini为扩展名的文件，放置于ini文件夹中。

进入src目录，运行`python alirss.py`后，会在export文件夹生成同名的xml文件。

## 全局配置文件

默认全局配置文件为src/alirss.conf，格式如下

    [PATH]
    ini_path = ../ini
    export_path = ../export

    [FETCH]
    interval = 1800

    [PUBLICATION]
    public = False
    reponame = your_repo_name

可以改变ini文件夹和export文件夹的位置，以及抓取间隔。

可以使用 `python alirss.py -c yourfile.conf`来使用指定的全局配置文件。

## 上传功能

如需自动上传xml至github等远程仓库，方法如下：

1. 在本机安装git，确保git已经加到PATH中。

2. 在github创建一个远程仓库，假设为 https://github.com/yourname/your_repo.git

3. 在命令行中进入export目录，建立本地仓库
    
        git init
        git add .
        git remote add your_repo_name https://yourname:yourpassword@github.com/yourname/your_repo.git    

    注意git remote add的时候*URL必须要带上用户名和密码*

4. 在全局配置文件中设置

        [PUBLICATION]
        public = True
        reponame = your_repo_name

这样，每次抓取完后就会自动将更新了的xml文件上传至远程仓库。

然后就可以让Google Reader抓取类似于https://raw.github.com/yourname/your_repo/master/xxx_site.xml的网址了。

## 未完成功能

* User Agent等的自定义
* 抓取使用Ajax的动态网页
* 代码单元测试

