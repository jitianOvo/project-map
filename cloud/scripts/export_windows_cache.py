from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWidgets import QApplication


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    options.output.parent.mkdir(parents=True, exist_ok=True)
    backup = options.output.parent / (options.output.stem + "-profile")
    if backup.exists():
        raise RuntimeError("缓存备份已经存在，不覆盖")
    shutil.copytree(options.profile, backup)

    class BlankPage(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<!doctype html><title>Cache export</title>")

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 18877), BlankPage)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    app = QApplication([])
    result = {"ok": False}

    class ExportPage(QWebEnginePage):
        def javaScriptConsoleMessage(self, _level, message, _line, _source):
            if not message.startswith("PROJECTMAP_EXPORT:"):
                return
            value = json.loads(message.split(":", 1)[1])
            if "error" in value:
                print("缓存导出失败：" + value["error"], file=sys.stderr)
            else:
                options.output.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
                result["ok"] = True
                print(json.dumps({"databases": len(value["databases"]), "documents": sum(len(item["docs"]) for item in value["databases"]), "images": sum(len(item["media"]) for item in value["databases"])}, ensure_ascii=False))
            app.quit()

    profile = QWebEngineProfile("project-map-cloud", app)
    profile.setPersistentStoragePath(str(backup))
    page = ExportPage(profile, app)
    script = r"""
    (async()=>{
      const read=(db,name)=>new Promise((resolve,reject)=>{
        const req=db.transaction(name,'readonly').objectStore(name).getAll();
        req.onsuccess=()=>resolve(req.result); req.onerror=()=>reject(req.error);
      });
      const output={databases:[]};
      for(const info of await indexedDB.databases()) {
        if(!info.name.startsWith('project-map-cloud:')) continue;
        const db=await new Promise((resolve,reject)=>{
          const req=indexedDB.open(info.name); req.onsuccess=()=>resolve(req.result); req.onerror=()=>reject(req.error);
        });
        const docs=await read(db,'docs'); const media=await read(db,'media');
        for(const item of media) for(const key of Object.keys(item)) if(item[key] instanceof Blob) {
          item[key]={mime:item[key].type,data:await new Promise(resolve=>{
            const reader=new FileReader(); reader.onload=()=>resolve(reader.result.split(',')[1]);reader.readAsDataURL(item[key]);
          })};
        }
        output.databases.push({endpoint:info.name.slice('project-map-cloud:'.length),docs,media});
        db.close();
      }
      console.log('PROJECTMAP_EXPORT:'+JSON.stringify(output));
    })().catch(error=>console.log('PROJECTMAP_EXPORT:'+JSON.stringify({error:String(error)})));
    """
    page.loadFinished.connect(lambda ok: page.runJavaScript(script) if ok else app.quit())
    page.load(QUrl("http://127.0.0.1:18877/index.html"))
    QTimer.singleShot(30000, app.quit)
    app.exec()
    page.deleteLater()
    app.processEvents()
    server.shutdown()
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
