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
                return d.get("split", True)
        return True

    def list_directories(self, files: bool = False):
        """List all registered directories."""
        if not self.config["directories"]:
            print("No directories are currently registered for indexing.")
        else:
            print(f"Registered directories ({len(self.config['directories'])}):")
            if files:
                for f in self.config.get("files", []):
                    print(f"  {f}")
            else:
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

    def add_directory(self, directory, split=True):
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

    def index_files(self, verbose: bool = False):
        """Index all files in registered directories."""
        print("Indexing files...")

        for d in self.config["directories"]:
            directory = d["path"]
            print(f"Processing directory: {directory}")

            indexed_files = self.get_indexed_files(directory)
            for file_path in indexed_files:
                rel_path = os.path.relpath(file_path, directory)
                key = f"{directory}/{rel_path}"
                content = self.read_file(file_path)
                file_hash = self.hash_content(content)

                # Check if file was already indexed and if it has changed
                if key in self.config["files"]:
                    old_hash = self.config["files"][key]
                    if old_hash == file_hash:
                        if verbose:
                            print(f"  Skipping unchanged file: {rel_path}")
                        continue

                split_enabled = d.get("split", True)
                existing_splits = set(
                    self.collection.get(where={"file_path": key}, include=[])["ids"]
                )

                if split_enabled:
                    split_parts = self.split_document_by_headers(content, file_path)
                    new_parts_docs = []
                    new_parts_metadatas = []
                    new_parts_ids = []

                    for part in split_parts:
                        part_content = part["content"]
                        part_hash = self.hash_content(part_content)
                        part_id = f"{key}#{part_hash}"

                        if part_id not in existing_splits:
                            new_parts_docs.append(part_content)
                            new_parts_metadatas.append(
                                {"dir_path": directory, "file_path": key}
                            )
                            new_parts_ids.append(part_id)
                            if verbose:
                                print(f"  Indexed (split): {part['title']}")
                        else:
                            existing_splits.remove(part_id)

                    if new_parts_ids:
                        self.collection.add(
                            documents=new_parts_docs,
                            metadatas=new_parts_metadatas,
                            ids=new_parts_ids,
                        )

                    if existing_splits:
                        self.collection.delete(ids=list(existing_splits))

                    self.config["files"][key] = file_hash
                else:
                    # Add entire file as one document
                    self.collection.upsert(
                        documents=[content],
                        metadatas=[{"dir_path": directory, "file_path": key}],
                        ids=[key],
                    )
                    existing_splits.remove(key)
                    if existing_splits:
                        self.collection.delete(ids=list(existing_splits))

                    self.config["files"][key] = file_hash
                print(f"  Indexed: {rel_path}")

            def _split_file(id):
                return id[: id.rfind("#")] if "#" in id else id

            indexed_files_set = set(indexed_files)
            dir_ids = self.collection.get(where={"dir_path": directory}, include=[])[
                "ids"
            ]
            old_ids = [k for k in dir_ids if _split_file(k) not in indexed_files_set]
            if old_ids:
                self.collection.delete(ids=old_ids)

        self.config["last_indexed_time"] = datetime.now().astimezone().isoformat()
        self.save_config()

    def read_file(self, file_path):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    def hash_content(self, content):
        """Calculate SHA256 hash of a string."""
        return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()

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
