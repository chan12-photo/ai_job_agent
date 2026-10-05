/* Clipboard and drop input only. Upload still uses the existing multipart form. */
(() => {
  "use strict";
  const form = document.getElementById("image-upload");
  const input = document.getElementById("images");
  const zone = document.getElementById("image-drop");
  const status = document.getElementById("image-input-status");
  const list = document.getElementById("image-selection");
  const submit = document.getElementById("image-upload-button");
  if (!form || typeof DataTransfer === "undefined") return;
  let selected = [];
  let sending = false;
  let pasted = 0;

  function render() {
    const transfer = new DataTransfer();
    selected.forEach(file => transfer.items.add(file));
    input.files = transfer.files;
    list.replaceChildren();
    selected.forEach((file, index) => {
      const row = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MiB `;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "제거";
      remove.setAttribute("aria-label", `${index + 1}번째 이미지 제거`);
      remove.disabled = sending;
      remove.addEventListener("click", () => {
        selected.splice(index, 1);
        render();
        status.textContent = `${selected.length}장 선택됨`;
      });
      row.append(label, remove);
      list.append(row);
    });
  }

  function add(files, clipboard = false) {
    if (sending) return;
    const incoming = Array.from(files);
    let error = "";
    if (!incoming.length) error = "이미지가 없습니다. 이미지 자체를 복사하거나 파일 선택을 사용해 주세요.";
    else if (incoming.some(file => clipboard
      ? !["image/png", "image/jpeg"].includes(file.type)
      : (!/\.(png|jpe?g)$/i.test(file.name) ||
        (file.type && !["image/png", "image/jpeg"].includes(file.type)))))
      error = "PNG·JPG·JPEG 이미지 파일만 추가할 수 있습니다.";
    else if (selected.length + incoming.length > 5) error = "최대 5장까지 추가할 수 있습니다. 먼저 불필요한 이미지를 제거하세요.";
    else if (incoming.some(file => !file.size || file.size > 8 * 1024 * 1024)) error = "빈 파일은 사용할 수 없으며, 한 장은 8 MiB 이하여야 합니다.";
    else if ([...selected, ...incoming].reduce((sum, file) => sum + file.size, 0) > 30 * 1024 * 1024)
      error = "이미지 합계는 30 MiB 이하여야 합니다.";
    if (!error) {
      selected.push(...incoming.map(file => clipboard
        ? new File([file], `캡처-${++pasted}.${file.type === "image/jpeg" ? "jpg" : "png"}`, {type: file.type})
        : file));
    }
    render();
    status.textContent = error || `${selected.length}장 선택됨 · 이미지 올리기를 누르면 원본 확인 화면으로 이동합니다.`;
  }

  input.addEventListener("change", () => add(input.files));
  document.addEventListener("paste", event => {
    if (event.target.closest("textarea, input:not([type=file]), [contenteditable=true]")) return;
    const files = Array.from(event.clipboardData?.items || [])
      .filter(item => item.kind === "file").map(item => item.getAsFile()).filter(Boolean);
    event.preventDefault();
    add(files, true);
  });
  document.addEventListener("dragover", event => {
    if (Array.from(event.dataTransfer?.types || []).includes("Files")) event.preventDefault();
  });
  zone.addEventListener("dragover", event => {
    event.preventDefault();
    zone.classList.add("dragging");
  });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragging"));
  document.addEventListener("drop", event => {
    event.preventDefault();
    zone.classList.remove("dragging");
    add(event.dataTransfer?.files || []);
  });
  form.addEventListener("submit", event => {
    if (sending) { event.preventDefault(); return; }
    sending = true;
    submit.disabled = true;
    submit.textContent = "이미지 확인 중…";
    render();
  });
  // Returning through browser history must not leave a disabled upload button.
  window.addEventListener("pageshow", () => {
    sending = false;
    submit.disabled = false;
    submit.textContent = "이미지 올리기";
    selected = Array.from(input.files || []);
    render();
  });
})();
