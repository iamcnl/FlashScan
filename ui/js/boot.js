if (localStorage.getItem('flashscan-theme') === 'dark') document.documentElement.dataset.theme = 'dark';

// A file dropped on the window would otherwise be opened by the browser, replacing the app.
for (const type of ['dragover', 'drop']) {
  window.addEventListener(type, (e) => {
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = 'none';
  });
}