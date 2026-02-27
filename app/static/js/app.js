function flashMessage(message) {
  const flash = document.getElementById('flash');
  if (!flash) return;
  flash.textContent = message;
  flash.classList.add('show');
  setTimeout(() => flash.classList.remove('show'), 1600);
}

let audioContext = null;
let audioUnlocked = false;

function unlockAudio() {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext) return;
    if (!audioContext) {
      audioContext = new AudioContext();
    }
    audioContext.resume();
    audioUnlocked = true;
  } catch (err) {
    audioUnlocked = false;
  }
}

function beep() {
  if (!audioUnlocked || !audioContext) return;
  const now = audioContext.currentTime;
  const oscillator = audioContext.createOscillator();
  const gain = audioContext.createGain();
  oscillator.type = 'sine';
  oscillator.frequency.value = 880;
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(0.2, now + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.15);
  oscillator.connect(gain);
  gain.connect(audioContext.destination);
  oscillator.start(now);
  oscillator.stop(now + 0.16);
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
    return { ok: true, queued: true, response: null, data: null };
  }
  const headers = { 'Content-Type': 'application/x-www-form-urlencoded' };
  if (form.dataset.expectJson === 'true') {
    headers.Accept = 'application/json';
    headers['X-Requested-With'] = 'XMLHttpRequest';
  }

  let response;
  try {
    response = await fetch(form.action, {
      method: form.method || 'post',
      headers,
      body: serializeForm(form),
    });
  } catch (error) {
    flashMessage('Submission failed');
    form.dispatchEvent(
      new CustomEvent('async-form-error', {
        detail: { form, response: null, data: null, error },
      })
    );
    return { ok: false, response: null, data: null, error };
  }

  let data = null;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    try {
      data = await response.json();
    } catch (error) {
      data = null;
    }
  }

  if (response.ok) {
    beep();
    flashMessage('Saved');
    if (form.dataset.resetOnSuccess === 'true') {
      form.reset();
    }
    if (form.dataset.refreshOnSuccess === 'true') {
      setTimeout(() => window.location.reload(), 400);
    }
    form.dispatchEvent(
      new CustomEvent('async-form-success', {
        detail: { form, response, data },
      })
    );
  } else {
    flashMessage('Submission failed');
    form.dispatchEvent(
      new CustomEvent('async-form-error', {
        detail: { form, response, data },
      })
    );
  }
  return { ok: response.ok, response, data };
}

window.addEventListener('online', flushQueue);
window.addEventListener('load', flushQueue);
document.addEventListener('click', unlockAudio, { once: true });
document.addEventListener('touchstart', unlockAudio, { once: true });
window.unlockAudio = unlockAudio;

window.addEventListener('submit', (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  if (form.dataset.asyncSubmit === 'true') {
    event.preventDefault();
    submitFormAsync(form);
  }
});
