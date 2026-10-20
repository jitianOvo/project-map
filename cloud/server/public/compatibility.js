(function () {
  if (
    !Array.prototype.at ||
    !window.crypto ||
    !crypto.subtle ||
    !window.HTMLDialogElement ||
    !HTMLDialogElement.prototype.showModal
  ) {
    window.addEventListener("DOMContentLoaded", function () {
      document.body.textContent =
        "当前系统网页组件版本过旧。请更新 Android System WebView / Chrome 后重新打开项目航图。";
      document.body.style.padding = "24px";
    });
  }
})();
