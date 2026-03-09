# Semantic Scholar Server Tools

This document lists all the tools available in the Semantic Scholar API Server.

## Paper-related Tools

### `paper_relevance_search`

Search for papers on Semantic Scholar using relevance-based ranking.

```json
{
  "query": "quantum computing",
  "fields": ["title", "abstract", "year", "authors"],
  "limit": 10
}
```

### `paper_bulk_search`

Bulk search for papers with advanced filtering and sorting options.

```json
{
  "query": "machine learning",
  "fields": ["title", "abstract", "authors"],
  "sort": "citationCount:desc"
}
```

### `paper_title_search`

Find a specific paper by matching its title.

```json
{
  "query": "Attention Is All You Need",
  "fields": ["title", "abstract", "authors", "year"]
}
```

### `paper_details`

Get detailed information about a specific paper by ID.

```json
{
  "paper_id": "649def34f8be52c8b66281af98ae884c09aef38b",
  "fields": ["title", "abstract", "authors", "citations"]
}
```

### `paper_batch_details`

Get details for multiple papers in one request.

```json
{
  "paper_ids": ["649def34f8be52c8b66281af98ae884c09aef38b", "ARXIV:2106.15928"],
  "fields": "title,abstract,authors"
}
```

### `paper_autocomplete`

Get autocomplete suggestions for a partial paper query.

```json
{
  "query": "large language mod"
}
```

### `snippet_search`

Search for matching snippets across paper content.

```json
{
  "query": "transformer attention",
  "fields": ["snippet.text", "paper.title"],
  "limit": 5,
  "authors": ["Ashish Vaswani"],
  "paper_ids": ["649def34f8be52c8b66281af98ae884c09aef38b"]
}
```

### `paper_authors`

Get the authors of a specific paper.

```json
{
  "paper_id": "649def34f8be52c8b66281af98ae884c09aef38b",
  "fields": ["name", "affiliations"]
}
```

### `paper_citations`

Get papers that cite a specific paper.

```json
{
  "paper_id": "649def34f8be52c8b66281af98ae884c09aef38b",
  "fields": ["title", "year", "authors"],
  "limit": 50
}
```

### `paper_references`

Get papers referenced by a specific paper.

```json
{
  "paper_id": "649def34f8be52c8b66281af98ae884c09aef38b",
  "fields": ["title", "year", "authors"],
  "limit": 50
}
```

## Author-related Tools

### `author_search`

Search for authors by name.

```json
{
  "query": "Albert Einstein",
  "fields": ["name", "affiliations", "paperCount"]
}
```

### `author_details`

Get detailed information about a specific author.

```json
{
  "author_id": "1741101",
  "fields": ["name", "affiliations", "papers", "citationCount"]
}
```

### `author_papers`

Get papers written by a specific author.

```json
{
  "author_id": "1741101",
  "fields": ["title", "year", "venue"],
  "limit": 50
}
```

### `author_batch_details`

Get details for multiple authors at once.

```json
{
  "author_ids": ["1741101", "1741102"],
  "fields": "name,affiliations,paperCount,citationCount"
}
```

## Recommendation Tools

### `get_paper_recommendations_single`

Get paper recommendations based on a single paper.

```json
{
  "paper_id": "649def34f8be52c8b66281af98ae884c09aef38b",
  "fields": "title,authors,year,abstract",
  "limit": 20
}
```

### `get_paper_recommendations_multi`

Get paper recommendations based on multiple papers.

```json
{
  "positive_paper_ids": [
    "649def34f8be52c8b66281af98ae884c09aef38b",
    "ARXIV:2106.15928"
  ],
  "negative_paper_ids": ["ARXIV:1805.02262"],
  "fields": "title,authors,year",
  "limit": 20
}
```

## Note

- The tool name in the error message (`read_paper`) does not exist in this server
- Use one of the tools listed above instead
- Always include the required parameters for each tool
