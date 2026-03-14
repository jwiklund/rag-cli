#!/usr/bin/env python3
"""
RAG (Retrieval-Augmented Generation) client using argparse and chromadb.
"""

import argparse
import os
import hashlib
from pathlib import Path
import chromadb
import json


class RAGClient:
    def __init__(self, db_path="rag_db"):
        self.db_path = db_path
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection_name = "rag_collection"
        try:
            self.collection = self.client.get_collection(self.collection_name)
        except:
            self.collection = self.client.create_collection(self.collection_name)
        
        # Track registered directories and file metadata
        self.config_file = os.path.join(db_path, "config.json")
        self.load_config()
    
    def load_config(self):
        """Load configuration from disk."""
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                self.config = json.load(f)
        else:
            self.config = {
                "registered_directories": [],
                "file_metadata": {}
            }
    
    def save_config(self):
        """Save configuration to disk."""
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def add_directory(self, directory):
        """Register a directory for indexing."""
        directory = os.path.abspath(directory)
        if directory not in self.config["registered_directories"]:
            self.config["registered_directories"].append(directory)
            self.save_config()
            print(f"Added directory: {directory}")
        else:
            print(f"Directory already registered: {directory}")
    
    def get_indexed_files(self, directory):
        """Get all .txt, .md, and .org files in the directory."""
        indexed_files = []
        for root, dirs, files in os.walk(directory):
            # Skip hidden directories and .venv directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '.venv']
            for file in files:
                if file.endswith(('.txt', '.md', '.org')):
                    full_path = os.path.join(root, file)
                    # Skip system files that shouldn't be indexed
                    if '.venv/' in full_path or '/.venv/' in full_path:
                        continue
                    indexed_files.append(full_path)
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
        
        # Keep track of files we've processed
        updated_files = set()
        
        for directory in self.config["registered_directories"]:
            print(f"Processing directory: {directory}")
            indexed_files = self.get_indexed_files(directory)
            
            for file_path in indexed_files:
                rel_path = os.path.relpath(file_path, directory)
                file_hash = self.get_file_hash(file_path)
                
                # Check if file was already indexed and if it has changed
                key = f"{directory}:{rel_path}"
                if key in self.config["file_metadata"]:
                    old_hash = self.config["file_metadata"][key].get("hash")
                    if old_hash == file_hash:
                        print(f"  Skipping unchanged file: {rel_path}")
                        continue
                
                # Read file content
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Add to ChromaDB collection
                self.collection.add(
                    documents=[content],
                    metadatas=[{"file_path": file_path}],
                    ids=[key]
                )
                
                # Update metadata
                self.config["file_metadata"][key] = {
                    "hash": file_hash,
                    "file_path": file_path
                }
                updated_files.add(key)
                print(f"  Indexed: {rel_path}")
        
        # Clean up files that were removed from directories
        current_files = set()
        for directory in self.config["registered_directories"]:
            indexed_files = self.get_indexed_files(directory)
            for file_path in indexed_files:
                rel_path = os.path.relpath(file_path, directory)
                key = f"{directory}:{rel_path}"
                current_files.add(key)
        
        # Remove old files that are no longer present
        removed_files = set(self.config["file_metadata"].keys()) - current_files
        if removed_files:
            print("Removing old files...")
            self.collection.delete(ids=list(removed_files))
            for key in removed_files:
                del self.config["file_metadata"][key]
        
        self.save_config()
        print(f"Indexed {len(updated_files)} files.")
    
    def search(self, query):
        """Search the index for matches."""
        results = self.collection.query(
            query_texts=[query],
            n_results=5,
        )
        
        if not results["documents"]:
            print("No results found.")
            return
        
        print(f"Results for query: '{query}'")
        print("-" * 50)
        
        # Process and display results
        for i, (doc, metadata) in enumerate(zip(results["documents"][0], results["metadatas"][0])):
            file_path = metadata.get("file_path", "Unknown")
            
            # Extract first line of content
            first_line = doc.split('\n')[0] if doc else ""
            
            print(f"Result {i+1}:")
            print(f"  File: {file_path}")
            print(f"  First line: {first_line}")
            print()


def main():
    parser = argparse.ArgumentParser(description="RAG client for indexing and searching documents")
    parser.add_argument('--rag_db', default='~/.rag.db', help='Path to the RAG database directory')
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # rag add command
    add_parser = subparsers.add_parser('add', help='Register directory for indexing')
    add_parser.add_argument('directory', type=str, help='Directory to register')
    
    # rag index command
    index_parser = subparsers.add_parser('index', help='Index all registered directories')
    
    # rag search command
    search_parser = subparsers.add_parser('search', help='Search the index')
    search_parser.add_argument('query', type=str, help='Search query')
    
    args = parser.parse_args()
    
    # Expand the ~ in the db path
    import os
    db_path = os.path.expanduser(args.rag_db)
    client = RAGClient(db_path=db_path)
    
    if args.command == 'add':
        client.add_directory(args.directory)
    elif args.command == 'index':
        client.index_files()
    elif args.command == 'search':
        client.search(args.query)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()