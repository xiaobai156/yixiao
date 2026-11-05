# 封存脚本（入库留档）

按父级 `AGENTS.md`「封存产生的目录、快照和记录必须入库并提交」的要求，封存操作使用的一次性脚本随仓库保存，脚本来源和归档结果见 `archived_sites.json`。

| 脚本 | 用途 |
| --- | --- |
| `roundtrip.py` | 校验三个 JSON 重新序列化后与原文逐字节一致，确认改写不会引入无关 diff |
| `archive_site.py` | 封存 `高手网论坛`（2026-11-04T18:35:19+08:00） |
| `archive_ssfh.py` | 封存 `盛世繁华`（2026-11-04T18:45:23+08:00），并清掉其在 308 期失败清单里的条目 |

## 做法

1. 前置条件：目标站必须恰好 1 条在 `sites.json`、恰好 1 条在 `recent_10_cache.json`、且不在封存档案中；任一不满足即退出，不做任何写入。
2. `sites` 条目补 `archived_at`（带 +08:00 时区）与 `archive_reason`（用户明确要求封存，不再抓取）；缓存条目整体镜像进 `archived_sites.json` 的 `cache_entries`，保留最后几期记录和当时的失败原因。
3. 三个 JSON 都用同目录临时文件 + `os.replace` 原子替换；`sites.json` 与 `recent_10_cache.json` 移除该站，封存站点此后不抓取、不写正式 TXT、不更新缓存。
4. 失败清单里的该站条目用项目自身 `zodiac_v2.output._failure_rows` / `_format_failure_rows` 重写，统计块随之重算。

恢复时逆序操作：从 `archived_sites.json` 取回站点与缓存条目写回，去掉 `archived_at` / `archive_reason`，再跑对应期只读复抓确认。
