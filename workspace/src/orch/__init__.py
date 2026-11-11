__version__ = "0.1.0"


def is_record_hook(argv: list[str]) -> bool:
    """`orch record [flags] hook ...`: a tool's hook call, which must end with exit 0 whatever happens (only
    --strict refuses). The first word after `record` that is not a flag (nor the value of `--by`) is `hook`.
    No imports: __main__ checks this before anything else is loaded."""
    if argv[:1] != ["record"]:
        return False
    rest = iter(argv[1:])
    for word in rest:
        if word == "--by":
            next(rest, None)
        elif not word.startswith("-"):
            return word == "hook"
    return False
