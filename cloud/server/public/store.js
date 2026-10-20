import { clone, fields, normalize, payload, uuid } from "./core.js";

export class Store {
  constructor(db) {
    this.db = db;
    this.tail = Promise.resolve();
  }
  static async open(endpoint) {
    const request = indexedDB.open("project-map-cloud:" + endpoint, 1);
    request.onupgradeneeded = () => {
      for (const name of ["docs", "media", "meta"])
        request.result.createObjectStore(name, { keyPath: "id" });
    };
    const db = await new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    return new Store(db);
  }
  async read(name, id) {
    await this.tail;
    return new Promise((resolve, reject) => {
      const tx = this.db.transaction(name, "readonly"),
        s = tx.objectStore(name),
        request = id === undefined ? s.getAll() : s.get(id);
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }
  mutate(name, id, update) {
    const job = this.tail.then(
      () =>
        new Promise((resolve, reject) => {
          const tx = this.db.transaction(name, "readwrite"),
            s = tx.objectStore(name),
            request = s.get(id);
          let value;
          request.onsuccess = () => {
            try {
              value = update(request.result);
              if (value !== undefined) s.put(value);
            } catch (error) {
              reject(error);
              tx.abort();
            }
          };
          tx.oncomplete = () => resolve(value);
          tx.onerror = () => reject(tx.error);
          tx.onabort = () => reject(tx.error || new Error("本地保存失败"));
        }),
    );
    this.tail = job.catch(() => {});
    return job;
  }
  put(name, value) {
    return this.mutate(name, value.id, () => value);
  }
  async create(document = {}) {
    const doc = {
      ...normalize(document),
      id: uuid(),
      revision: 0,
      base: { ...fields },
      dirty: true,
      generation: 1,
      pending: null,
    };
    await this.put("docs", doc);
    return doc;
  }
  edit(id, changes) {
    return this.mutate("docs", id, (doc) => {
      if (!doc) throw new Error("项目不存在");
      return {
        ...doc,
        ...normalize({ ...doc, ...changes }),
        dirty: true,
        generation: doc.generation + 1,
      };
    });
  }
  async prepare(id) {
    const entry = await this.mutate("docs", id, (doc) => {
      if (!doc?.dirty || doc.pending) return doc;
      return {
        ...doc,
        pending: {
          id: doc.id,
          op_id: uuid(),
          base_revision: doc.revision,
          document: clone(payload(doc)),
          generation: doc.generation,
        },
      };
    });
    return entry?.pending;
  }
  meta(id, value) {
    return value === undefined
      ? this.read("meta", id).then((entry) => entry?.value)
      : this.put("meta", { id, value });
  }
}
