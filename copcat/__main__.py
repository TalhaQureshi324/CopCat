if __name__ == "__main__":
    # spawn-safe guard: required on Windows so ProcessPoolExecutor children
    # don't re-execute the CLI
    from .cli import main
    main()
