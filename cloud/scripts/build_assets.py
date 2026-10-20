from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]


def build():
    for target in (ROOT / "server/public", ROOT / "android/assets/web", ROOT / "windows/web"):
        target.mkdir(parents=True, exist_ok=True)
        for source in (ROOT / "web").iterdir():
            if source.is_file():
                shutil.copy2(source, target / source.name)
        vendor = target / "vendor"
        vendor.mkdir(exist_ok=True)
        for package, source, name in (
            ("markdown-it", "dist/browser/markdown-it.umd.min.js", "markdown-it.min.js"),
            ("dompurify", "dist/purify.min.js", "purify.min.js"),
        ):
            shutil.copy2(ROOT / "node_modules" / package / source, vendor / name)
            for license_name in ("LICENSE", "LICENSE.txt"):
                license_path = ROOT / "node_modules" / package / license_name
                if license_path.exists():
                    shutil.copy2(license_path, vendor / (package + "-LICENSE.txt"))
    print("三端离线资源已生成。")


if __name__ == "__main__":
    build()
