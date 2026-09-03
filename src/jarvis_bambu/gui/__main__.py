import multiprocessing
import sys
from pathlib import Path


def main() -> int:
    # Required by frozen Windows executables using spawn/ProcessPoolExecutor.
    multiprocessing.freeze_support()
    if len(sys.argv) == 3 and sys.argv[1] == "--build-smoke":
        from jarvis_bambu.build_smoke import run_build_smoke

        run_build_smoke(Path(sys.argv[2]))
        return 0
    from jarvis_bambu.gui.app import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
