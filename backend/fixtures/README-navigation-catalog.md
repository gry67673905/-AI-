# 导航目录 CSV

管理员通过 `POST /api/v1/admin/navigation-catalog/import?dry_run=true` 上传 UTF-8 CSV。`dry_run` 默认为 `true`，会完成整文件解析、事项与部门归属校验，但不会写入数据库；确认报告无错误后再用 `dry_run=false` 导入。

导入上限为 1 MiB、1000 行。整份文件在单个数据库事务中写入：任何一行失败都不会产生部分更新。CSV 对文件中出现的每个事项采用“全量快照”语义：网点按“网点编码”更新或创建并启用本次关联，该事项原有但本次未列出的关联会被停用；不会因为某个事项移除关联而全局停用仍可供其他事项使用的网点。旧 `window_id` 兼容字段同步指向本次仍活动且优先级最高的网点。坐标系固定为 GCJ02；`VERIFIED` 数据必须填写“来源”和带时区的 ISO-8601“核验时间”。

公开接口 `GET /api/v1/services/{service_id}/navigation-options` 不接收用户位置，只返回已发布事项关联的活动网点。`DEMO` 网点带有不可用于真实导航的提示。

- `navigation_catalog_template.csv`：空白固定表头模板。
- `navigation_catalog_demo.csv`：仅用于本地演示的示例数据。
- `navigation_catalog_chengdu_device_test.csv`：成都真机验收用的六条关联；身份证补领和公积金事项各使用三个独立合成网点，坐标为 GCJ02，绝非真实办事地址。
