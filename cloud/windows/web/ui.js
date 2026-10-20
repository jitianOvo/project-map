export const $ = (selector) => document.querySelector(selector);
export const el = (tag, text = "", className = "") => {
  const node = document.createElement(tag);
  node.textContent = text;
  node.className = className;
  return node;
};
let toastTimer;
export function toast(message) {
  $("#toast").textContent = message;
  $("#toast").classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $("#toast").classList.remove("show"), 3500);
}
export function field(label, type = "text", value = "", options = []) {
  const wrapper = el("label", label, "form-field");
  const input = document.createElement(
    type === "textarea" ? "textarea" : type === "select" ? "select" : "input",
  );
  if (input.tagName === "INPUT") input.type = type;
  for (const [id, title] of options) {
    const option = el("option", title);
    option.value = id;
    input.append(option);
  }
  if (type === "checkbox") input.checked = !!value;
  else input.value = value;
  wrapper.append(input);
  return { wrapper, input };
}
export async function dialog(title, content, accept, button = "确定") {
  const modal = $("#dialog");
  if (modal.open) modal.close();
  $("#dialogTitle").textContent = title;
  $("#dialogContent").replaceChildren(...content);
  $("#dialogConfirm").textContent = button;
  $("#dialogConfirm").disabled = false;
  modal.showModal();
  return new Promise((resolve) => {
    const close = () => modal.close();
    $("#dialogCancel").onclick = close;
    $("#dialogClose").onclick = close;
    $("#dialogForm").onsubmit = async (event) => {
      event.preventDefault();
      $("#dialogConfirm").disabled = true;
      try {
        await accept();
        modal.close();
      } catch (error) {
        toast(error.message);
      } finally {
        $("#dialogConfirm").disabled = false;
      }
    };
    modal.onclose = () => resolve();
    setTimeout(
      () => {
        if ([modal, document.body, $("#dialogClose")].includes(document.activeElement))
          content[0]?.querySelector("input,select,textarea")?.focus();
      },
      40,
    );
  });
}
export function contextMenu(event, items) {
  event.preventDefault();
  const menu = $("#contextMenu");
  menu.replaceChildren();
  for (const [label, handler] of items) {
    const button = el("button", label);
    button.onclick = () => {
      menu.hidden = true;
      Promise.resolve(handler()).catch((error) => toast(error.message));
    };
    menu.append(button);
  }
  menu.hidden = false;
  menu.style.left =
    Math.min(event.clientX, innerWidth - menu.offsetWidth - 9) + "px";
  menu.style.top =
    Math.min(event.clientY, innerHeight - menu.offsetHeight - 9) + "px";
}
document.addEventListener("pointerdown", (event) => {
  if (!event.target.closest("#contextMenu")) $("#contextMenu").hidden = true;
});
