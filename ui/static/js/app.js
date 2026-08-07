// ClipIt Mobile Dashboard JavaScript Engine

let currentAccountFilter = 'all';
let currentClips = [];
let editingClipId = null;

document.addEventListener('DOMContentLoaded', () => {
  initIcons();
  fetchPendingClips();
  fetchSystemStatus();

  // Poll system status every 5 seconds
  setInterval(fetchSystemStatus, 5000);
});

function initIcons() {
  if (window.lucide) {
    lucide.createIcons();
  }
}

// Fetch pending clips from REST API
async function fetchPendingClips() {
  try {
    const url = `/api/clips/pending?account_id=${encodeURIComponent(currentAccountFilter)}`;
    const response = await fetch(url);
    const data = await response.json();

    if (data.status === 'success') {
      currentClips = data.clips;
      renderClips(currentClips);
    }
  } catch (error) {
    console.error('Error fetching clips:', error);
    showToast('Failed to load pending clips', 'error');
  }
}

// Fetch system & daemon metrics
async function fetchSystemStatus() {
  try {
    const response = await fetch('/api/system/status');
    const data = await response.json();

    if (data.status === 'online' && data.daemon) {
      const { battery_percent, pending_queue, is_charging } = data.daemon;
      
      const batteryText = document.getElementById('batteryText');
      const queueText = document.getElementById('queueText');
      
      if (batteryText) {
        batteryText.innerText = `${battery_percent}%${is_charging ? ' ⚡' : ''}`;
      }
      if (queueText) {
        queueText.innerText = pending_queue;
      }
    }
  } catch (error) {
    console.warn('System status fetch warning:', error);
  }
}

// Render 9:16 Video Cards
function renderClips(clips) {
  const grid = document.getElementById('clipsGrid');
  const emptyState = document.getElementById('emptyState');

  if (!clips || clips.length === 0) {
    grid.innerHTML = '';
    emptyState.classList.remove('hidden');
    return;
  }

  emptyState.classList.add('hidden');

  grid.innerHTML = clips.map(clip => {
    const viralityClass = clip.virality_score >= 90 ? 'virality-high' : '';
    const videoSrc = clip.video_path ? `/media/${clip.video_path}` : '';
    
    return `
      <div id="card-${clip.id}" class="clip-card glass-panel flex flex-col">
        <!-- 9:16 Vertical Video Container -->
        <div class="video-container">
          <!-- Account Badge -->
          <span class="account-badge">${escapeHtml(clip.account_id || '@clipit')}</span>
          
          <!-- Virality Score Badge -->
          <div class="virality-badge ${viralityClass}">
            <i data-lucide="flame" class="w-4 h-4 fill-current"></i>
            <span>${clip.virality_score}% Virality</span>
          </div>

          ${videoSrc ? `
            <video controls playsinline preload="metadata" class="w-full h-full object-cover">
              <source src="${videoSrc}" type="video/mp4">
              Your browser does not support HTML5 video player.
            </video>
          ` : `
            <div class="video-placeholder">
              <div class="w-12 h-12 rounded-full bg-purple-500/20 border border-purple-500/30 flex items-center justify-center mb-2 text-purple-400">
                <i data-lucide="play" class="w-6 h-6 ml-0.5"></i>
              </div>
              <p class="font-bold text-sm text-white mb-1">9:16 Vertical Preview</p>
              <p class="text-xs text-gray-400">${clip.duration || 45}s • ${clip.start_time}s–${clip.end_time}s</p>
            </div>
          `}
        </div>

        <!-- Card Content -->
        <div class="card-content flex-1">
          <h4 class="card-title" title="${escapeHtml(clip.source_title)}">
            ${escapeHtml(clip.source_title)}
          </h4>

          <div class="card-hook">
            <span class="font-bold text-purple-300">Hook:</span> ${escapeHtml(clip.hook_summary || 'Top performing high-converting moment.')}
          </div>

          <!-- Action Bar (1-Tap Approval) -->
          <div class="action-bar mt-2">
            <button onclick="approveClip('${clip.id}')" class="btn-action btn-approve" title="1-Tap Approve">
              <i data-lucide="check-circle-2" class="w-4 h-4"></i> Approve
            </button>
            
            <button onclick="openModal('${clip.id}')" class="btn-action btn-edit" title="Edit Subtitles">
              <i data-lucide="edit-3" class="w-4 h-4"></i> Edit
            </button>

            <button onclick="rejectClip('${clip.id}')" class="btn-action btn-reject" title="1-Tap Reject">
              <i data-lucide="x-circle" class="w-4 h-4"></i>
            </button>
          </div>
        </div>
      </div>
    `;
  }).join('');

  initIcons();
}

// Account Filter Handler
function filterAccount(accountId) {
  currentAccountFilter = accountId;
  
  // Update Pill UI
  const pills = document.querySelectorAll('.pill-btn');
  pills.forEach(btn => {
    btn.classList.remove('active');
    if (btn.innerText.toLowerCase().includes(accountId.replace('@', '').toLowerCase()) || 
       (accountId === 'all' && btn.innerText.includes('All'))) {
      btn.classList.add('active');
    }
  });

  fetchPendingClips();
}

// 1-Tap Approve Clip Handler (Optimistic Removal)
async function approveClip(clipId) {
  const card = document.getElementById(`card-${clipId}`);
  if (card) {
    card.classList.add('card-approved-anim');
  }

  showToast('⚡ Clip Approved! Queue updated.', 'success');

  try {
    const response = await fetch(`/api/clips/${clipId}/approve`, { method: 'POST' });
    const data = await response.json();
    
    setTimeout(() => {
      currentClips = currentClips.filter(c => c.id !== clipId);
      renderClips(currentClips);
    }, 350);
  } catch (error) {
    console.error('Approve clip error:', error);
    showToast('Failed to approve clip', 'error');
    fetchPendingClips();
  }
}

// 1-Tap Reject Clip Handler (Optimistic Removal)
async function rejectClip(clipId) {
  const card = document.getElementById(`card-${clipId}`);
  if (card) {
    card.classList.add('card-rejected-anim');
  }

  showToast('Clip rejected and dismissed.', 'info');

  try {
    const response = await fetch(`/api/clips/${clipId}/reject`, { method: 'POST' });
    const data = await response.json();

    setTimeout(() => {
      currentClips = currentClips.filter(c => c.id !== clipId);
      renderClips(currentClips);
    }, 350);
  } catch (error) {
    console.error('Reject clip error:', error);
    showToast('Failed to reject clip', 'error');
    fetchPendingClips();
  }
}

// Open Subtitle Quick Editor Modal
function openModal(clipId) {
  const clip = currentClips.find(c => c.id === clipId);
  if (!clip) return;

  editingClipId = clipId;
  const modal = document.getElementById('clipModal');
  const subtitlesList = document.getElementById('subtitlesList');
  const videoPlayer = document.getElementById('modalVideoPlayer');
  const videoSource = document.getElementById('modalVideoSource');

  if (clip.video_path) {
    videoSource.src = `/media/${clip.video_path}`;
    videoPlayer.load();
  } else {
    videoSource.src = '';
  }

  const subs = clip.subtitles && clip.subtitles.length > 0 ? clip.subtitles : [
    { start: 0.0, end: 3.0, text: 'Sample subtitle caption text' }
  ];

  subtitlesList.innerHTML = subs.map((s, idx) => `
    <div class="subtitle-row">
      <input type="number" step="0.1" value="${s.start}" class="time-input sub-start" placeholder="Start">
      <span class="text-xs text-gray-500">to</span>
      <input type="number" step="0.1" value="${s.end}" class="time-input sub-end" placeholder="End">
      <input type="text" value="${escapeHtml(s.text)}" class="text-input sub-text" placeholder="Subtitle text...">
      <button onclick="this.parentElement.remove()" class="text-gray-500 hover:text-red-400 p-1">&times;</button>
    </div>
  `).join('');

  modal.classList.add('active');
}

function closeModal() {
  const modal = document.getElementById('clipModal');
  const videoPlayer = document.getElementById('modalVideoPlayer');
  if (videoPlayer) {
    videoPlayer.pause();
  }
  modal.classList.remove('active');
  editingClipId = null;
}

function addSubtitleRow() {
  const subtitlesList = document.getElementById('subtitlesList');
  const div = document.createElement('div');
  div.className = 'subtitle-row';
  div.innerHTML = `
    <input type="number" step="0.1" value="0.0" class="time-input sub-start" placeholder="Start">
    <span class="text-xs text-gray-500">to</span>
    <input type="number" step="0.1" value="3.0" class="time-input sub-end" placeholder="End">
    <input type="text" value="" class="text-input sub-text" placeholder="New subtitle line...">
    <button onclick="this.parentElement.remove()" class="text-gray-500 hover:text-red-400 p-1">&times;</button>
  `;
  subtitlesList.appendChild(div);
}

// Save Updated Subtitles via REST API
async function saveSubtitles() {
  if (!editingClipId) return;

  const rows = document.querySelectorAll('#subtitlesList .subtitle-row');
  const subtitles = [];

  rows.forEach(row => {
    const start = parseFloat(row.querySelector('.sub-start').value) || 0.0;
    const end = parseFloat(row.querySelector('.sub-end').value) || 0.0;
    const text = row.querySelector('.sub-text').value.trim();

    if (text) {
      subtitles.push({ start, end, text });
    }
  });

  try {
    const response = await fetch(`/api/clips/${editingClipId}/update_subtitles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subtitles })
    });
    
    const data = await response.json();
    if (data.status === 'success') {
      showToast('Subtitles updated successfully!', 'success');
      closeModal();
      fetchPendingClips();
    }
  } catch (error) {
    console.error('Error saving subtitles:', error);
    showToast('Failed to save subtitles', 'error');
  }
}

// Helper Toast Notifications
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type === 'success' ? 'border-emerald-500/50 text-emerald-300' : ''}`;
  toast.innerText = message;

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, 2500);
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
}
