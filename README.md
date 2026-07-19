# 12306 余票监控

买了无座票想蹲二等座/一等座？这个脚本轮询 12306 官方余票接口，一旦你关注的车次放出指定席别的余票，立刻推送到你手机（Bark / Server酱 / PushPlus），同时终端响铃 + 桌面弹窗。

> ⚠️ 只做监控和提醒，**不会自动下单**。收到通知后请立即打开 12306 APP 抢购/改签。
> ⚠️ 必须在**国内网络**环境下运行，12306 会封锁海外和云服务器 IP。

## 快速开始

```bash
pip install requests
cp config.example.json config.json
# 编辑 config.json 填入你的车次信息
python ticket_monitor.py --config config.json
```

## 配置说明（config.json）

| 字段 | 说明 |
|------|------|
| `date` | 乘车日期，格式 `YYYY-MM-DD` |
| `from` / `to` | 出发/到达站，用 12306 上的**标准站名**（如 `北京南`、`上海虹桥`，不是 `北京`） |
| `trains` | 要监控的车次列表，如 `["G1", "G3"]`；留空 `[]` 则监控该区间全部车次 |
| `seats` | 要监控的席别，支持：二等座、一等座、商务座、特等座、硬座、软座、硬卧、软卧、高级软卧、动卧、无座 |
| `interval_seconds` | 查询间隔（秒），最低 10，**建议 ≥ 30**，太频繁可能被 12306 限流封 IP |
| `renotify_minutes` | 同一车次同一席别重复提醒的间隔（分钟），避免连环轰炸 |
| `notify.desktop` | 是否弹桌面通知（Mac/Windows/Linux 均支持） |
| `notify.bark_key` | iPhone 推荐：App Store 装 [Bark](https://apps.apple.com/cn/app/bark/id1403753865)，把 App 里的 key 填进来 |
| `notify.serverchan_sendkey` | 微信推送：[Server酱](https://sct.ftqq.com/) 的 SendKey |
| `notify.pushplus_token` | 微信推送备选：[PushPlus](https://www.pushplus.plus/) 的 token |

三种手机推送渠道任选其一即可（都留空则只有终端响铃和桌面弹窗）。

## 拿到票之后

- 已有无座票 → 在 12306 APP 里走「**改签**」，直接换成刚放出的坐票，不用先退票。
- 开车前提示：发车前 48 小时~15 天退改规则不同，改签不收手续费（票价差额多退少补）。

## 其他建议

- **官方候补**是成功率最高的方式：在 12306 APP 里对目标车次席别提交候补订单，系统有退票会自动出票，优先级高于任何人工捡漏。建议候补 + 本脚本同时上。
- 放票/捡漏高峰：整点/半点放票、开车前 48 小时和 24 小时（改签退票集中）、发车前 1~2 小时，这些时间点最容易刷到。
- 12306 会不定期更换接口路径和风控策略，脚本已内置接口自动探测和会话重建；如果长时间持续查询失败，多半是 IP 被临时限流，停 10 分钟或换网络再跑。
