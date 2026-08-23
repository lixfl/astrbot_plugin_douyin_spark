# 抖音续火花助手 - AstrBot 插件

一个自托管的抖音「续火花」自动化工具，集成到 AstrBot 中。部署在自己的服务器上，每天定时自动给指定好友发送私信，维持聊天火花（🔥）不熄灭。

## 功能特性

- **网页管理界面**：在 AstrBot WebUI 中完整管理——上传登录态、勾选续火花好友、设置发送时间、手动发送/干跑测试、查看日志
- **好友一键勾选**：从抖音聊天列表自动读取好友（含各自火花天数），勾选即用，免手动输入
- **每日定时发送**：随机时间窗口 + 随机文案库 + 好友间随机间隔，模拟真人节奏
- **防错发保护**：点击后校验右侧会话标题，确认切对人再发送；搜索兜底直接打开会话
- **真实发送校验**：消息离开输入框才算发出，失败自动重试一次
- **当日自动补发**：本轮有失败时，约 45 分钟后自动只对失败好友补发一次（每天最多一次）
- **限流检测**：识别"操作频繁 / 安全验证"提示，命中立即停止本轮，避免误发
- **掉线提醒**：登录态失效时状态标红，重新扫码上传即可恢复
- **命令行控制**：支持通过机器人命令查看状态、触发发送、获取好友列表等

## 安装方法

### 1. 安装依赖

```bash
cd /path/to/AstrBot
pip install playwright apscheduler pydantic
playwright install chromium
```

### 2. 安装插件

将插件目录复制到 AstrBot 的插件目录：

```bash
cp -r astrbot_plugin_douyin_spark /path/to/AstrBot/data/plugins/
```

或者使用 git：

```bash
cd /path/to/AstrBot/data/plugins
git clone https://github.com/your-repo/astrbot_plugin_douyin_spark.git
```

### 3. 重启 AstrBot

重启 AstrBot 以加载插件。

## 使用方法

### 1. 获取登录态 (state.json)

在**有界面的电脑上**（Windows/macOS/Linux 桌面环境）运行：

```bash
cd /path/to/AstrBot/data/plugins/astrbot_plugin_douyin_spark
python -m core.extract_cookie
```

- 会弹出浏览器窗口，打开抖音网页版
- 使用手机抖音 App 扫码登录
- 登录成功后，会自动在插件数据目录生成 state.json

### 2. 上传登录态

在 AstrBot WebUI 中：
1. 进入 **插件管理** → **抖音续火花助手** → **页面**
2. 点击"选择 state.json"上传刚才生成的文件
3. 点击"上传登录态"

### 3. 配置好友与消息

1. 点击"获取聊天列表"从抖音读取好友（含火花天数）
2. 勾选需要续火花的好友，点击"把勾选结果写入名单"
3. 在"消息模板"中设置发送内容（每行一条，随机选择）
4. 点击"保存"

### 4. 设置定时任务

在"定时设置"标签页：
- **每天发送时间**：建议晚上（如 21:00）
- **时间抖动窗口**：0-30 分钟内随机开始，避免每天同一秒触发风控
- **好友间隔**：相邻好友发送间隔 6-12 秒
- **最大发送数**：每次最多发给多少好友（建议 10-20）
- **自动补发**：开启后失败好友会在 45 分钟后自动重试

### 5. 测试与启用

- 点击"干跑测试"验证流程（不真实发送）
- 点击"立即发送"手动触发一次
- 定时任务会在设定时间自动运行

## 命令控制

在聊天中发送以下命令（需管理员权限）：

| 命令 | 别名 | 说明 |
|------|------|------|
| /续火花状态 | /spark_status | 查看运行状态 |
| /续火花发送 | /spark_send | 立即发送续火花 |
| /续火花测试 | /spark_dry | 干跑测试 |
| /续火花获取好友 | /spark_fetch | 从抖音获取聊天列表 |
| /续火花好友 | /spark_friends | 查看已配置好友 |
| /续火花设置 | /spark_config | 查看当前配置 |
| /续火花帮助 | /spark_help | 显示帮助 |

## 注意事项

1. **仅限个人自用**：自动化发私信违反抖音社区公约，存在被风控、限流甚至封号的风险，**使用后果自负**
2. **低频少量**：建议好友数 <= 20，每天 1 条，间隔 >= 6 秒
3. **登录态维护**：登录态通常几天到几周过期一次，过期后需重新运行提取脚本并上传
4. **服务器 IP**：建议使用国内同城机房服务器，海外 IP 极易触发验证码/安全验证
5. **页面结构变更**：抖音网页版更新可能导致选择器失效，需及时更新代码
6. **内存要求**：Chromium 无头模式需要一定内存，1G 内存服务器建议配置 2G swap

## 致谢

发送流程与部署思路借鉴了以下开源项目：

- [douyin-cloud-streak](https://github.com/Yuriz132/douyin-cloud-streak)
- [DouYinSparkFlow](https://github.com/2061360308/DouYinSparkFlow)
- [TikTokAutoSparkWeb](https://github.com/DkoBot/TikTokAutoSparkWeb)

## License

[MIT](./LICENSE)
