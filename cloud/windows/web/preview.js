export class Preview {
  constructor(viewport, onImage, onTask) {
    this.viewport = viewport;
    this.content = viewport.querySelector("article");
    this.images = new Map();
    this.zoom = 100;
    this.md = window.markdownit({ html: true, breaks: true, linkify: true });
    const validate = this.md.validateLink.bind(this.md);
    this.md.validateLink = (value) =>
      /^cloud-media:\/\/[a-f0-9]{64}$/.test(value) || validate(value);
    const image = this.md.renderer.rules.image.bind(this.md.renderer.rules);
    this.md.renderer.rules.image = (tokens, index, options, env, self) => {
      const src = tokens[index].attrGet("src");
      const cached = src.match(
        /^(?:cloud-media:\/\/|Media\/)([a-f0-9]{64})(?:\.(?:png|jpg|jpeg|gif|webp))?$/,
      );
      if (cached) {
        const id = cached[1];
        tokens[index].attrSet("data-media-id", id);
        tokens[index].attrSet("src", this.images.get(id) || "");
      }
      return image(tokens, index, options, env, self);
    };
    viewport.addEventListener("dblclick", (event) => {
      if (event.target.tagName === "IMG" && event.target.src)
        onImage(event.target.src);
    });
    viewport.addEventListener("click", (event) => {
      const task = event.target.closest("[data-task-line]");
      if (task) onTask(+task.dataset.taskLine);
      const link = event.target.closest("a");
      if (link) {
        event.preventDefault();
        if (/^https?:/.test(link.href))
          window.open(link.href, "_blank", "noopener");
      }
    });
  }
  html(text) {
    const tokens = this.md.parse(text, {});
    let line = 0;
    for (let i = 0; i < tokens.length; i++) {
      if (tokens[i].map) line = tokens[i].map[0];
      if (
        tokens[i].type === "inline" &&
        /^\[[ xX]\] /.test(tokens[i].content)
      ) {
        const checked = /^\[[xX]\]/.test(tokens[i].content);
        tokens[i].children = this.md.parseInline(
          tokens[i].content.slice(4),
          {},
        )[0].children;
        const check = new this.md.Token("html_inline", "", 0);
        check.content = `<button class="task-check${checked ? " done" : ""}" data-task-line="${line}" aria-label="切换任务状态">${checked ? "✓" : " "}</button>`;
        tokens[i].children.unshift(check);
      }
      if (tokens[i].type === "heading_open")
        tokens[i].attrSet("data-source-line", line);
    }
    return DOMPurify.sanitize(
      this.md.renderer.render(tokens, this.md.options, {}),
      {
        USE_PROFILES: { html: true },
        ADD_ATTR: [
          "data-priority",
          "data-media-id",
          "data-source-line",
          "data-task-line",
        ],
        FORBID_TAGS: ["style", "form", "input", "iframe"],
        FORBID_ATTR: ["style"],
        ALLOWED_URI_REGEXP:
          /^(?:(?:https?|mailto|tel|blob):|[^a-z]|[a-z+.-]+(?:[^a-z+.\-:]|$))/i,
      },
    );
  }
  render(text) {
    this.text = text;
    const top = this.viewport.scrollTop,
      left = this.viewport.scrollLeft,
      oldHeight = this.content.offsetHeight;
    const template = document.createElement("template");
    template.innerHTML = this.html(text);
    this.content.style.minHeight = oldHeight + "px";
    patch(this.content, template.content);
    this.content.style.zoom = this.zoom / 100;
    this.viewport.scrollTop = top;
    this.viewport.scrollLeft = left;
    requestAnimationFrame(() => {
      this.content.style.minHeight = "";
      this.viewport.scrollTop = top;
      this.viewport.scrollLeft = left;
    });
  }
  setImage(id, url) {
    this.images.set(id, url);
    const top = this.viewport.scrollTop,
      left = this.viewport.scrollLeft;
    for (const image of this.content.querySelectorAll(
      `[data-media-id="${id}"]`,
    )) {
      if (image.src !== url) image.src = url;
    }
  }
  setZoom(value) {
    this.zoom = value;
    this.content.style.zoom = value / 100;
  }
}

function patch(target, source) {
  const desired = [...source.childNodes];
  for (let i = 0; i < desired.length; i++) {
    const old = target.childNodes[i],
      next = desired[i];
    if (!old) {
      target.appendChild(next.cloneNode(true));
      continue;
    }
    if (old.nodeType !== next.nodeType || old.nodeName !== next.nodeName) {
      old.replaceWith(next.cloneNode(true));
      continue;
    }
    if (old.nodeType === Node.TEXT_NODE) {
      if (old.nodeValue !== next.nodeValue) old.nodeValue = next.nodeValue;
      continue;
    }
    if (old.nodeType !== Node.ELEMENT_NODE) continue;
    for (const attribute of [...old.attributes])
      if (!next.hasAttribute(attribute.name))
        old.removeAttribute(attribute.name);
    for (const attribute of [...next.attributes])
      if (old.getAttribute(attribute.name) !== attribute.value)
        old.setAttribute(attribute.name, attribute.value);
    patch(old, next);
  }
  while (target.childNodes.length > desired.length) target.lastChild.remove();
}
