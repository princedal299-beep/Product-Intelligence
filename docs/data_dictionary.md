# Data Dictionary

A simple reference for the core product fields in `Export_Merchandise_Feeds_us-en_1_2026-09-28T18-02-19-762Z.csv`.

| Field Name | Type | Description | Example |
|---|---|---|---|
| `sku` | String | Unique product variant ID (Primary Key) | `SR5098RD-YG-AA-9x7` |
| `SKU` | String | Parent style ID grouping variants | `SR5098RD` |
| `Product Name` | String | Product title | `Emerald-Cut Ruby Cathedral Ring` |
| `price (in USD)` | Number | Retail price in USD | `6919` |
| `In Stock` | String | Availability status (`true` = in stock) | `true` |
| `jewelry_type` | String | Category (`Rings`, `Bands`, `Tiaras`) | `Rings` |
| `metal_type` | String | Metal material and karatage | `14K Yellow Gold` |
| `metal_weight` | Number | Metal weight in grams | `5.5` |
| `stone1_name` | String | Primary gemstone name | `Ruby` |
| `stone1_shape` | String | Center stone cut shape | `Emerald Cut` |
| `stone1_grade` | String | Quality grade (Color / Clarity) | `AA` |
| `Total Carat Weight` | Number | Total gemstone weight across all stones | `3.16` |
| `Image path` | URL | Link to product image | `https://assets.angara.com/...jpg` |
| `Description` | String | Product description | `Handcrafted in 14k yellow gold...` |

> *Note: The CSV contains 160 columns in total, but 140+ are repetitive secondary stone slots (`stone2`–`stone16`) or empty attributes.*
