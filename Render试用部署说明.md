# Render 异地协作试用

2026年11月5日。用于两三位同事短期试走流程，不需要登录。当前只完成部署配置和本地验证，尚未创建 Render 服务；获得实际网址后再交同事使用。

PDF 导入更新：新版包含 `pdf_invoice.py` 和 `requirements.txt` 中的 pdfplumber 依赖。旧试用站需将更新包的全部源文件提交到同一 GitHub 仓库，再在 Render 执行 Manual Deploy → Deploy latest commit；构建会自动安装 PDF 依赖。没有上传真实 PDF 样例。更新免费实例前请导出想保留的试用记录。

## 试用方式

打开部署后 Render 提供的 HTTPS 网址，角色选“审核”，即可操作全部环节。所有访问者共用同一份测试订单。保留必填项检查、节点顺序、批准后锁定和过期版本拒绝修改。没有真实账号，历史仍按选择的演示角色记录，不能分辨具体人员。

一个人保存后，另一个人点击右上角“刷新资料”查看；刷新前先保存自己的填写。若同一产品已被他人更新，旧版本提交会提示刷新，应核对最新资料后重填。邮件仍只生成草稿，需要实际手动发送。云端新老板审批链接自动使用该试用站的 HTTPS 地址。

只初始化三笔 DEMO 演示订单，可自行创建测试订单。不会上传本机实际 Invoice、截图、邮件和数据库。网址公开且没有登录，任何持有网址的人均可查看、修改、下载及导出；仅上传用于测试的虚构资料。

## 准备代码仓库

运行 `python build_trial_bundle.py`，生成 `dist/ecobag-workbench-render-trial.zip`。压缩包仅含清单中的程序与说明，不含 data、imports、日志、真实附件或整个 EcoBag SEO 工作区。

解压后将这些文件放到一个专门的 GitHub 私有代码仓库根目录，并提交。Render 通过 GitHub 仓库拉取程序，不是直接上传 ZIP。若使用大仓库的子目录，须在 Render 设置相应 Root Directory；本包按独立仓库根目录准备。

## 创建免费试用服务

在 Render 控制台 New → Web Service，连接上述仓库。设置：

| 项目 | 值 |
| --- | --- |
| 服务名称 | ecobag-workbench-trial；重名可加后缀 |
| Language / Runtime | Python 3 |
| Instance Type | Free |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `python -u server.py` |
| Health Check Path | `/healthz` |
| Auto-Deploy | Off；避免试用中因代码更新触发重置 |
| PYTHON_VERSION | `3.13.9` |
| WORKBENCH_PUBLIC_DEMO | `1` |
| WORKBENCH_EPHEMERAL_STORAGE | `1` |

也可用仓库中的 render.yaml 建立 Blueprint，配置内容相同。此文件放在独立仓库根目录。无需添加磁盘、数据库、邮箱凭据或 QuickBooks 凭据。不调整已有正式服务。

程序自动读取 Render 的 PORT、RENDER_EXTERNAL_URL，监听 0.0.0.0；只接受本机健康访问或所配置站点的 Host / Origin。无需手动猜网址。不配置公网模式时，原来的 `启动工作台.cmd` 仍只监听本机。

创建服务后，等待状态 Live，打开 Render 给出的网址。确认页面显示“在线试用”，仅有三笔 DEMO 订单；新浏览器默认审核角色，能新建、保存和刷新。然后复制这个网址给参与测试的同事。手册为 `该网址/manual.html`。

## 免费版数据和结束试用

Render Free 服务闲置15分钟会休眠，再次打开需要等待唤醒。免费实例的本地文件不是持久存储，重启、休眠或重新部署后测试记录可能丢失；不可用于保存唯一一份业务资料。试用中和结束前通过“导出订单与附件”保存 ZIP；目前导出供查阅，没有导入恢复界面。

测试完成后，在 Render 暂停该试用服务即可停止访问。需要保留测试记录跨重启时，再单独决定持久化方案及费用。本稿没有开通付费资源。

官方说明：[Render Free](https://render.com/docs/free)、[Web Services](https://render.com/docs/web-services)。
