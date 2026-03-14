#!/usr/bin/env python3
"""
RAG (Retrieval-Augmented Generation) client using argparse and chromadb.
"""

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import chromadb


class RAGClient:
    def __init__(self, db_path):
        self.db_path = db_path
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection_name = "rag_collection"
        try:
            self.collection = self.client.get_collection(self.collection_name)
        except:
            self.collection = self.client.create_collection(self.collection_name)

        # Track registered directories
        self.config_file = os.path.join(db_path, "config.json")
        self.load_config()

    def load_config(self):
        """Load configuration from disk: {directories: [{path, split}], files: {path: {hash}}, last_indexed_time: str}."""
        if os.path.exists(self.config_file):
            with open(self.config_file, "r") as f:
                self.config = json.load(f)
        else:
            self.config = {"directories": [], "files": {}, "last_indexed_time": None}

    def save_config(self):
        """Save configuration to disk."""
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(self.config, f, indent=2)

    def is_split_enabled(self, directory):
        """Check if split mode is enabled for a directory."""
        directory = os.path.abspath(directory)
        for d in self.config["directories"]:
            if d["path"] == directory:
                return d.get("split", False)
        return False

    def list_directories(self):
        """List all registered directories."""
        if not self.config["directories"]:
            print("No directories are currently registered for indexing.")
        else:
            print(f"Registered directories ({len(self.config['directories'])}):")
            for d in self.config["directories"]:
                print(f"  {d['path']}")

    def split_document_by_headers(self, content, file_path):
        """Split markdown/org document by headers (# for markdown, * for org)."""
        ext = Path(file_path).suffix.lower()
        is_markdown = ext == ".md"
        is_org = ext == ".org"

        parts = []
        current_title = ""
        current_content_lines = []

        def flush_part():
            nonlocal current_title, current_content_lines
            if current_title and current_content_lines:
                parts.append(
                    {
                        "title": current_title,
                        "content": "\n".join(current_content_lines).rstrip() + "\n",
                    }
                )
            current_content_lines = []
            current_title = ""

        for line in content.split("\n"):
            stripped = line.strip()

            if is_markdown and stripped.startswith("# "):
                level = len(stripped) - len(stripped.lstrip("#"))
                if level == 1 and current_title:
                    flush_part()
                current_title = stripped.lstrip("#").strip()
                current_content_lines = [stripped]
            elif is_org and stripped.startswith("* "):
                level = len(stripped) - len(stripped.lstrip("*"))
                if level == 1 and current_title:
                    flush_part()
                current_title = stripped.lstrip("*").strip()
                current_content_lines = [stripped]
            elif current_title:
                current_content_lines.append(line)

        flush_part()
        return parts

    def del_directory(self, directory):
        """Remove a directory from registered directories."""
        directory = os.path.abspath(directory)
        self.config["directories"] = [
            d for d in self.config["directories"] if d["path"] != directory
        ]

        # Clean up file metadata for this directory
        prefixes = [f"{directory}/", f"{directory}\\"]
        keys_to_remove = [
            k for k in self.config["files"] if any(k.startswith(p) for p in prefixes)
        ]
        for key in keys_to_remove:
            del self.config["files"][key]

        self.save_config()
        print(f"Removed directory: {directory}")

    def add_directory(self, directory, split=False):
        """Register a directory for indexing."""
        directory = os.path.abspath(directory)
        for d in self.config["directories"]:
            if d["path"] == directory:
                print(f"Directory already registered: {directory}")
                return

        self.config["directories"].append({"path": directory, "split": split})
        self.save_config()
        print(f"Added directory: {directory}")

    def get_indexed_files(self, directory):
        """Get all .txt, .md, and .org files in the directory."""
        indexed_files = []
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for file in files:
                if file.endswith((".txt", ".md", ".org")):
                    indexed_files.append(os.path.join(root, file))
        return indexed_files

    def get_file_hash(self, file_path):
        """Calculate SHA256 hash of a file."""
        hash_sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()

    def index_files(self):
        """Index all files in registered directories."""
        print("Indexing files...")

        for d in self.config["directories"]:
            directory = d["path"]
            print(f"Processing directory: {directory}")
            indexed_files = self.get_indexed_files(directory)
            dir_files = set()

            for file_path in indexed_files:
                rel_path = os.path.relpath(file_path, directory)
                key = f"{directory}/{rel_path}"
                file_hash = self.get_file_hash(file_path)

                # Check if file was already indexed and if it has changed
                if key in self.config["files"]:
                    old_hash = self.config["files"][key]
                    if old_hash == file_hash:
                        print(f"  Skipping unchanged file: {rel_path}")
                        dir_files.add(key)
                        continue

                # Read file content
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                if d.get("split", False):
                    split_parts = self.split_document_by_headers(content, file_path)
                    current_ids = self.collection.query(
                        query_texts=[""], where={"file_path": key}, include=[]
                    )["ids"][0]
                    if current_ids:
                        self.collection.delete(ids=current_ids)
                    for i, part in enumerate(split_parts):
                        part_key = f"{key}#{i:03d}"
                        self.collection.add(
                            documents=[part["content"]],
                            metadatas=[{"dir_path": directory, "file_path": key}],
                            ids=[part_key],
                        )
                        print(f"  Indexed (split): {part['title']}")
                    self.config["files"][key] = file_hash
                    dir_files.add(key)
                else:
                    # Add entire file as one document
                    self.collection.add(
                        documents=[content],
                        metadatas=[{"dir_path": directory, "file_path": key}],
                        ids=[key],
                    )
                    self.config["files"][key] = file_hash
                    dir_files.add(key)
                    print(f"  Indexed: {rel_path}")

            def _split_file(id):
                return id[: id.rfind("#")] if "#" in id else id

            all_ids = self.collection.query(
                query_texts=[""], where={"dir_path": directory}, include=[]
            )["ids"][0]
            old_ids = [k for k in all_ids if _split_file(k) not in dir_files]
            if old_ids:
                self.collection.delete(ids=old_ids)

        self.config["last_indexed_time"] = datetime.now().astimezone().isoformat()
        self.save_config()

    def needs_implicit_reindex(self):
        """Check if implicit reindexing is needed based on time threshold."""
        last_indexed = self.config.get("last_indexed_time")
        if last_indexed is None:
            return True

        try:
            last_dt = datetime.fromisoformat(last_indexed)
            now = datetime.now(timezone.utc)
            if last_dt.tzinfo is not None:
                last_dt = last_dt.astimezone(timezone.utc)
            return (now - last_dt).total_seconds() / 3600 >= 1.0
        except Exception:
            return False

    def search(self, query, output_format=None):
        """Search the index for matches."""
        if self.needs_implicit_reindex():
            print(
                "Implicit reindexing triggered (last index > 1 hour ago or never indexed)..."
            )
            self.index_files()

        results = self.collection.query(
            query_texts=[query],
            n_results=5,
        )
        results = results or {"documents": [[]], "metadatas": [[]]}
        results_data = []
        for doc, metadata in zip(results["documents"][0], results["metadatas"][0]):
            # Read first line from file instead of from stored doc
            file_path = metadata.get("file_path", "")
            text = "\n".join(doc.split("\n")[0:4]).strip()
            results_data.append({"file_path": file_path, "text": text})

        if output_format == "json":
            print(json.dumps(results_data, indent=2))
        elif output_format == "csv":
            writer = csv.writer(sys.stdout)
            writer.writerow(["file_path", "text"])
            for i, r in enumerate(results_data):
                writer.writerow([r["file_path"], r["text"].replace("\n", "\\n")])
        else:
            for r in results_data:
                print(r["file_path"], ":")
                print(r["text"])
                print()


def main():
    parser = argparse.ArgumentParser(
        description="RAG client for indexing and searching documents"
    )
    parser.add_argument(
        "--rag-db", default="~/.rag.db", help="Path to the RAG database directory"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # rag add command
    add_parser = subparsers.add_parser("add", help="Register directory for indexing")
    add_parser.add_argument("directory", type=str, help="Directory to register")
    add_parser.add_argument(
        "--split",
        action="store_true",
        help="Split document by headers (# for markdown, * for org) and index each part individually",
    )

    # rag index command
    index_parser = subparsers.add_parser(
        "index", help="Index all registered directories"
    )

    # rag list command
    list_parser = subparsers.add_parser("list", help="List all registered directories")

    # rag remove command
    remove_parser = subparsers.add_parser(
        "remove", help="Remove a directory from registered directories"
    )
    remove_parser.add_argument("directory", type=str, help="Directory to remove")

    # rag search command
    search_parser = subparsers.add_parser("search", help="Search the index")
    search_parser.add_argument("query", nargs="*", type=str, help="Search query")
    search_parser.add_argument(
        "--json", action="store_true", help="Output results in JSON format"
    )
    search_parser.add_argument(
        "--csv", action="store_true", help="Output results in CSV format"
    )

    args = parser.parse_args()
    db_path = os.path.expanduser(args.rag_db)
    client = RAGClient(db_path=db_path)

    if args.command == "add":
        client.add_directory(args.directory, split=args.split)
    elif args.command == "list":
        client.list_directories()
    elif args.command == "remove":
        client.del_directory(args.directory)
    elif args.command == "index":
        client.index_files()
    elif args.command == "search":
        # Determine output format
        if args.json:
            output_format = "json"
        elif args.csv:
            output_format = "csv"
        else:
            output_format = None
        client.search(" ".join(args.query), output_format)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
