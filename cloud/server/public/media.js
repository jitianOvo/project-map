import { $, toast } from "./ui.js";
import { native } from "./api.js";
import { normalize, payload } from "./core.js";

export function encode(bytes) {
  let result = "";
  for (let i = 0; i < bytes.length; i += 16384)
    result += String.fromCharCode(...bytes.subarray(i, i + 16384));
  return btoa(result);
}
export function decode(value) {
  return Uint8Array.from(atob(value), (char) => char.charCodeAt(0));
}
export function download(name, mime, data) {
  const bytes =
    typeof data === "string" ? new TextEncoder().encode(data) : data;
  if (native()?.exportFile) {
    native().exportFile(name, mime, encode(bytes));
    return;
  }
  const url = URL.createObjectURL(new Blob([bytes], { type: mime })),
    link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 20000);
}
export class Media {
  constructor(store, api, preview) {
    Object.assign(this, { store, api, preview });
    this.urls = new Map();
    this.loading = new Set();
    this.scale = 1;
    $("#imageClose").onclick = () => $("#lightbox").close();
    $("#imageZoomIn").onclick = () => this.zoom(1.15);
    $("#imageZoomOut").onclick = () => this.zoom(1 / 1.15);
    $("#imageZoomReset").onclick = () => this.zoom(1, true);
    $("#imageViewport").addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        this.zoom(event.deltaY < 0 ? 1.12 : 1 / 1.12);
      },
      { passive: false },
    );
    let distance = 0;
    $("#imageViewport").addEventListener(
      "touchmove",
      (event) => {
        if (event.touches.length === 2) {
          event.preventDefault();
          const next = Math.hypot(
            event.touches[0].clientX - event.touches[1].clientX,
            event.touches[0].clientY - event.touches[1].clientY,
          );
          if (distance) this.zoom(next / distance);
          distance = next;
        }
      },
      { passive: false },
    );
    $("#imageViewport").addEventListener("touchend", () => (distance = 0));
  }
  async cache(file) {
    if (file.size > 12 * 1024 * 1024) throw new Error("单张图片最多 12 MB");
    const data = new Uint8Array(await file.arrayBuffer());
    let mime = "";
    if (data[0] === 137 && data[1] === 80) mime = "image/png";
    else if (data[0] === 255 && data[1] === 216) mime = "image/jpeg";
    else if (new TextDecoder().decode(data.slice(0, 3)) === "GIF")
      mime = "image/gif";
    else if (new TextDecoder().decode(data.slice(8, 12)) === "WEBP")
      mime = "image/webp";
    if (!mime) throw new Error("只支持 PNG、JPEG、GIF、WebP 图片");
    const id = [...new Uint8Array(await crypto.subtle.digest("SHA-256", data))]
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    const previous = await this.store.read("media", id);
    if (!previous)
      await this.store.put("media", {
        id,
        mime,
        data: encode(data),
        uploaded: false,
      });
    const extension = {
      "image/png": "png",
      "image/jpeg": "jpg",
      "image/gif": "gif",
      "image/webp": "webp",
    }[mime];
    return {
      id,
      markdown: `![${(file.name || "图片").replace(/[\[\]\r\n]/g, "")}](Media/${id}.${extension})`,
    };
  }
  async hydrate(text) {
    const ids = [
      ...text.matchAll(
        /(?:cloud-media:\/\/|Media\/)([a-f0-9]{64})(?:\.(?:png|jpg|jpeg|gif|webp))?/g,
      ),
    ].map((match) => match[1]);
    for (const id of new Set(ids)) {
      if (this.urls.has(id)) {
        this.preview.setImage(id, this.urls.get(id));
        continue;
      }
      if (this.loading.has(id)) continue;
      this.loading.add(id);
      try {
        let image = await this.store.read("media", id);
        if (!image && this.api.token) {
          const remote = await this.api.request("api/media/" + id);
          image = { id, ...remote, uploaded: true };
          await this.store.put("media", image);
        }
        if (image) {
          const url = URL.createObjectURL(
            new Blob([decode(image.data)], { type: image.mime }),
          );
          this.urls.set(id, url);
          this.preview.setImage(id, url);
        }
      } catch (error) {
        console.warn("图片待同步", error.message);
      } finally {
        this.loading.delete(id);
      }
    }
  }
  open(url) {
    const image = $("#largeImage");
    image.onload = () => {
      const view = $("#imageViewport");
      this.scale = Math.min(
        1,
        (view.clientWidth - 30) / image.naturalWidth,
        (view.clientHeight - 30) / image.naturalHeight,
      );
      this.zoom(1);
    };
    image.src = url;
    $("#lightbox").showModal();
  }
  zoom(factor, reset = false) {
    this.scale = reset ? 1 : Math.max(0.05, Math.min(8, this.scale * factor));
    $("#largeImage").style.width =
      $("#largeImage").naturalWidth * this.scale + "px";
    $("#imageZoomReset").textContent = Math.round(this.scale * 100) + "%";
  }
  async exportBackup() {
    const docs = (await this.store.read("docs")).map((doc) => ({
      id: doc.id,
      ...payload(doc),
    }));
    for (const doc of docs) await this.hydrate(doc.content);
    const media = await this.store.read("media"),
      available = new Set(media.map((image) => image.id)),
      needed = new Set(
        docs.flatMap((doc) =>
          [
            ...doc.content.matchAll(
              /(?:cloud-media:\/\/|Media\/)([a-f0-9]{64})/g,
            ),
          ].map((match) => match[1]),
        ),
      );
    const missing = [...needed].filter((id) => !available.has(id));
    if (missing.length)
      throw new Error(
        `还有 ${missing.length} 张图片未下载，完整备份暂未导出。请联网同步后重试。`,
      );
    download(
      "项目航图备份-" + new Date().toISOString().slice(0, 10) + ".json",
      "application/json",
      JSON.stringify({
        format: "project-map-backup",
        version: 1,
        created: new Date().toISOString(),
        documents: docs,
        media: media.map(({ id, mime, data }) => ({ id, mime, data })),
      }),
    );
  }
  async importBackup(text) {
    const backup = JSON.parse(text);
    if (
      backup.format !== "project-map-backup" ||
      !Array.isArray(backup.documents) ||
      !Array.isArray(backup.media) ||
      backup.documents.length > 2000
    )
      throw new Error("不是有效的项目航图备份");
    const documents = backup.documents.map(normalize);
    const images = [];
    for (const image of backup.media) {
      const file = new File([decode(image.data)], "图片", { type: image.mime }),
        cached = await this.cache(file);
      if (cached.id !== image.id) throw new Error("备份图片校验失败");
      images.push(cached);
    }
    for (const doc of documents) {
      await this.store.create({ ...payload(doc), title: doc.title });
    }
    toast("备份已导入为独立项目，没有覆盖原项目");
  }
}
