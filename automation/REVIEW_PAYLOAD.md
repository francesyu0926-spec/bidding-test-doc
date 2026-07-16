# saveReview Payload Format

Discovered via probing `POST api/publicity/saveReview` (PM token required).

## Transport

- **Content-Type**: `application/x-www-form-urlencoded` (nested PHP-style keys)
- **Do not** send JSON body — nested `review_data` arrays fail with PHP foreach errors unless encoded as form fields.

## Top-level fields

| Field | Required | Description |
|-------|----------|-------------|
| `project_id` | yes | Publicity project ID |

## review_data[] (array of scoring categories)

Each index `N` is one review category. Category scores must sum to **100**.

| Field | Required | Description |
|-------|----------|-------------|
| `review_data[N][publicity_id]` | yes | Same as `project_id` |
| `review_data[N][section_id]` | yes | Section ID |
| `review_data[N][cate_id]` | yes | Project category (e.g. 1=工程) |
| `review_data[N][pattern_id]` | yes | Bidding pattern (e.g. 1=公开招标) |
| `review_data[N][type]` | yes | 1=技术评分, 2=商务评分, 3=报价评分 |
| `review_data[N][title]` | yes | Category display name |
| `review_data[N][score]` | yes | Category max points |
| `review_data[N][factor]` | yes | Weight (usually equals `score`) |
| `review_data[N][standard]` | yes | Scoring criteria text |
| `review_data[N][price_method]` | type=3 | Quote method: 1=方法一, 2=方法二, 3=手工录入 |
| `review_data[N][price_n]` | type=3, method=1 | n value for method 1 (must be > 3) |

## review_data[N][items][M] (sub-items for type 1/2)

| Field | Required | Description |
|-------|----------|-------------|
| `title` | yes | Sub-item name |
| `factor` | yes | Sub-item weight |
| `score` | yes | Sub-item max points |
| `standard` | yes | Sub-item scoring criteria |

Sub-item scores within a category should sum to the category `score`.

## Default configuration (total = 100)

| Category | type | score | Sub-items |
|----------|------|-------|-----------|
| 技术评分 | 1 | 60 | 技术方案 30 + 实施计划 30 |
| 商务评分 | 2 | 10 | 商务响应 10 |
| 报价评分 | 3 | 30 | price_method=1, price_n=5 |

## Example (abbreviated)

```
project_id=2060
review_data[0][publicity_id]=2060
review_data[0][section_id]=1890
review_data[0][cate_id]=1
review_data[0][pattern_id]=1
review_data[0][type]=1
review_data[0][title]=技术评分
review_data[0][score]=60
review_data[0][factor]=60
review_data[0][standard]=对投标人技术方案、实施能力等进行综合评价
review_data[0][items][0][title]=技术方案
review_data[0][items][0][factor]=30
review_data[0][items][0][score]=30
review_data[0][items][0][standard]=方案完整可行，满足采购需求
...
review_data[2][type]=3
review_data[2][title]=报价评分
review_data[2][score]=30
review_data[2][price_method]=1
review_data[2][price_n]=5
```

## Code helpers

- `zjgj_client.build_review_form_data()` — builds nested form tuples
- `ZjgjClient.save_review_config()` — saves default or custom categories
- `automation/configure_review_tables.py` — batch configure projects 2060–2063

## Verification

No reliable GET endpoint for review table read-back was found (`reviewList` returns 500). Success is confirmed by API response `code=1, msg=保存成功`. Re-save is idempotent.
