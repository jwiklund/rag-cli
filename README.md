# RAG Client

A Python-based Retrieval-Augmented Generation client using ChromaDB for indexing and searching documents.

## Features

- Index `.txt`, `.md`, and `.org` files from registered directories
- Search through indexed content
- Track file changes and only re-index modified files
- Persistent storage using ChromaDB
- Configurable database path

## Usage

```bash
# Register a directory for indexing
rag add <directory>

# Index all files in registered directories
rag index

# Search the index
rag search <query>
```

## Command-line Options

```bash
# Specify custom database path (default: ~/.rag.db)
rag --rag_db /path/to/db <command>
```

## Commands

- `add <directory>` - Register directory for indexing
- `index` - Index all registered directories  
- `search <query>` - Search the index

## Requirements

- Python 3.6+
- chromadb
- argparse (built-in)

## Installation

```bash
uv sync
```

## Example

```bash
# Register current directory for indexing
uv run rag add .

# Index all files
uv run rag index

# Search for content
uv run rag search "your search query"
```