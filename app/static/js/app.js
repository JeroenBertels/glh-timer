function flashMessage(message) {
  const flash = document.getElementById('flash');
  if (!flash) return;
  flash.textContent = message;
  flash.classList.add('show');
  setTimeout(() => flash.classList.remove('show'), 1600);
}

function beep() {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    const context = new AudioContext();
    const oscillator = context.createOscillator();
    oscillator.type = 'sine';
    oscillator.frequency.value = 880;
    oscillator.connect(context.destination);
    oscillator.start();
    setTimeout(() => {
      oscillator.stop();
      context.close();
    }, 150);
  } catch (err) {
    // Audio might be blocked; fallback to flash only.
  }
}

function serializeForm(form) {
  const data = new URLSearchParams();
  new FormData(form).forEach((value, key) => {
    data.append(key, value.toString());
  });
  return data;
}

function queueSubmission(form) {
  const payload = {
    url: form.action,
    method: form.method || 'post',
    body: serializeForm(form).toString(),
    queuedAt: new Date().toISOString(),
  };
  const queue = JSON.parse(localStorage.getItem('glhTimerQueue') || '[]');
  queue.push(payload);
  localStorage.setItem('glhTimerQueue', JSON.stringify(queue));
}

async function flushQueue() {
  const queue = JSON.parse(localStorage.getItem('glhTimerQueue') || '[]');
  if (!queue.length) return;
  const remaining = [];
  for (const item of queue) {
    try {
      const response = await fetch(item.url, {
        method: item.method.toUpperCase(),
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: item.body,
      });
      if (!response.ok) {
        remaining.push(item);
      }
    } catch (err) {
      remaining.push(item);
    }
  }
  localStorage.setItem('glhTimerQueue', JSON.stringify(remaining));
  if (remaining.length !== queue.length) {
    flashMessage('Queued submissions sent');
  }
}

async function submitFormAsync(form) {
  if (!navigator.onLine && form.dataset.offlineQueue === 'true') {
    queueSubmission(form);
    flashMessage('Offline: submission queued');
    return;
  }
  const response = await fetch(form.action, {
    method: form.method || 'post',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: serializeForm(form),
  });
  if (response.ok) {
    beep();
    flashMessage('Saved');
    if (form.dataset.resetOnSuccess === 'true') {
      form.reset();
    }
  } else {
    flashMessage('Submission failed');
  }
}

window.addEventListener('online', flushQueue);
window.addEventListener('load', flushQueue);

window.addEventListener('submit', (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  if (form.dataset.asyncSubmit === 'true') {
    event.preventDefault();
    submitFormAsync(form);
  }
});
