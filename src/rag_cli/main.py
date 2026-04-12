import argparse
import os
import rag_cli.rag as rag


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
        dest="split",
        help="Split document by headers (# for markdown, * for org) and index each part individually (default)",
    )
    add_parser.add_argument(
        "--no-split",
        action="store_false",
        dest="split",
        help="Do not split documents, index entire file as one",
    )
    add_parser.set_defaults(split=True)

    # rag index command
    index_parser = subparsers.add_parser(
        "index", help="Index all registered directories"
    )
    index_parser.add_argument(
        "--verbose", action="store_true", help="Print detailed indexing information"
    )

    # rag list command
    list_parser = subparsers.add_parser("list", help="List all registered directories")
    list_parser.add_argument(
        "--files", action="store_true", help="Also list indexed files"
    )

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
    client = rag.RAGClient(db_path=db_path)

    if args.command == "add":
        client.add_directory(args.directory, split=args.split)
    elif args.command == "list":
        client.list_directories(args.files)
    elif args.command == "remove":
        client.del_directory(args.directory)
    elif args.command == "index":
        client.index_files(args.verbose)
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
