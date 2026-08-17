/* Pronunciation Trainer - Frontend logic
 *
 * Core capabilities:
 * - Direct microphone recording (16 kHz WAV)
 * - Sample Audio Library (52 test samples for minimal pairs, sentences, words, synthetic controls)
 * - 1-Click test & score on sample audio
 * - Drag & drop or local file upload for WAV/MP3/OGG files
 * - Word & phoneme level visual assessment with coach feedback
 */

const $ = (id) => document.getElementById(id);

// Dynamic API resolution: falls back to http://127.0.0.1:8000 when opened via file:// or non-8000 ports
const API = (window.location.protocol === "file:" || (window.location.port && window.location.port !== "8000"))
  ? "http://127.0.0.1:8000"
  : "";

let TARGET = "";
let THRESHOLDS = { good: 80, fair: 60 };
let LAST = null;          // last assessment payload
let MY_BUFFER = null;     // decoded AudioBuffer of the scored recording
let ACTIVE_WORD = null;
let ACTIVE_FILTER = "sentence";
let SEARCH_QUERY = "";

// Embedded initial manifest: SENTENCES PRIORITIZED FIRST
let SAMPLES = [
  {"file": "sentences/cmu_arctic_us_female_a0001.wav", "text": "Author of the danger trail, Philip Steels, etc.", "category": "sentence", "speaker": "CMU Arctic (US Female - slt)", "type": "human"},
  {"file": "sentences/cmu_arctic_us_male_a0001.wav", "text": "Author of the danger trail, Philip Steels, etc.", "category": "sentence", "speaker": "CMU Arctic (US Male - bdl)", "type": "human"},
  {"file": "sentences/cmu_arctic_scottish_male_a0001.wav", "text": "Author of the danger trail, Philip Steels, etc.", "category": "sentence", "speaker": "CMU Arctic (Scottish Male - awb)", "type": "human"},
  {"file": "sentences/cmu_arctic_us_female_a0002.wav", "text": "Not at this particular case, Tom, apologized Whittemore.", "category": "sentence", "speaker": "CMU Arctic (US Female - slt)", "type": "human"},
  {"file": "sentences/cmu_arctic_us_male_a0003.wav", "text": "For the twentieth time that evening the two men shook hands.", "category": "sentence", "speaker": "CMU Arctic (US Male - bdl)", "type": "human"},
  {"file": "sentences/cmu_arctic_us_female_a0004.wav", "text": "Lord, but I'm glad to see you again, Phil.", "category": "sentence", "speaker": "CMU Arctic (US Female - slt)", "type": "human"},
  {"file": "sentences/cmu_arctic_us_male_a0004.wav", "text": "Lord, but I'm glad to see you again, Phil.", "category": "sentence", "speaker": "CMU Arctic (US Male - bdl)", "type": "human"},
  {"file": "sentences/cmu_arctic_us_female_a0005.wav", "text": "Will we ever forget it.", "category": "sentence", "speaker": "CMU Arctic (US Female - slt)", "type": "human"},
  {"file": "sentences/cmu_arctic_scottish_male_a0005.wav", "text": "Will we ever forget it.", "category": "sentence", "speaker": "CMU Arctic (Scottish Male - awb)", "type": "human"},
  {"file": "sentences/loose_lips_sink_ships.wav", "text": "Loose lips sink ships.", "category": "sentence", "speaker": "Wikimedia Commons (US English)", "type": "human"},
  {"file": "synthetic/syn_she_sells_seashells.wav", "text": "she sells seashells by the seashore", "category": "sentence", "speaker": "eSpeak Synthetic Sentence", "type": "synthetic_espeak"},
  {"file": "synthetic/syn_cup_of_coffee.wav", "text": "I would like a cup of coffee", "category": "sentence", "speaker": "eSpeak Synthetic Sentence", "type": "synthetic_espeak"},
  {"file": "words/sheep.wav", "text": "sheep", "category": "minimal_pair", "focus": "iː", "type": "human_native"},
  {"file": "words/ship.wav", "text": "ship", "category": "minimal_pair", "focus": "ɪ", "type": "human_native"},
  {"file": "words/feel.wav", "text": "feel", "category": "minimal_pair", "focus": "iː", "type": "human_native"},
  {"file": "words/fill.wav", "text": "fill", "category": "minimal_pair", "focus": "ɪ", "type": "human_native"},
  {"file": "words/beat.wav", "text": "beat", "category": "minimal_pair", "focus": "iː", "type": "human_native"},
  {"file": "words/bit.wav", "text": "bit", "category": "minimal_pair", "focus": "ɪ", "type": "human_native"},
  {"file": "words/three.wav", "text": "three", "category": "minimal_pair", "focus": "θ", "type": "human_native"},
  {"file": "words/tree.wav", "text": "tree", "category": "minimal_pair", "focus": "t", "type": "human_native"},
  {"file": "words/think.wav", "text": "think", "category": "minimal_pair", "focus": "θ", "type": "human_native"},
  {"file": "words/sink.wav", "text": "sink", "category": "minimal_pair", "focus": "s", "type": "human_native"},
  {"file": "words/rice.wav", "text": "rice", "category": "minimal_pair", "focus": "ɹ", "type": "human_native"},
  {"file": "words/lice.wav", "text": "lice", "category": "minimal_pair", "focus": "l", "type": "human_native"},
  {"file": "words/road.wav", "text": "road", "category": "minimal_pair", "focus": "ɹ", "type": "human_native"},
  {"file": "words/load.wav", "text": "load", "category": "minimal_pair", "focus": "l", "type": "human_native"},
  {"file": "words/right.wav", "text": "right", "category": "minimal_pair", "focus": "ɹ", "type": "human_native"},
  {"file": "words/light.wav", "text": "light", "category": "minimal_pair", "focus": "l", "type": "human_native"},
  {"file": "words/very.wav", "text": "very", "category": "minimal_pair", "focus": "v", "type": "human_native"},
  {"file": "words/berry.wav", "text": "berry", "category": "minimal_pair", "focus": "b", "type": "human_native"},
  {"file": "words/vine.wav", "text": "vine", "category": "minimal_pair", "focus": "v", "type": "human_native"},
  {"file": "words/wine.wav", "text": "wine", "category": "minimal_pair", "focus": "w", "type": "human_native"},
  {"file": "words/vest.wav", "text": "vest", "category": "minimal_pair", "focus": "v", "type": "human_native"},
  {"file": "words/west.wav", "text": "west", "category": "minimal_pair", "focus": "w", "type": "human_native"},
  {"file": "words/correct.wav", "text": "correct", "category": "lesson_word", "focus": "ɹ", "type": "human_native"},
  {"file": "words/collect.wav", "text": "collect", "category": "lesson_word", "focus": "l", "type": "human_native"},
  {"file": "words/mother.wav", "text": "mother", "category": "lesson_word", "focus": "ð", "type": "human_native"},
  {"file": "words/birthday.wav", "text": "birthday", "category": "lesson_word", "focus": "θ", "type": "human_native"},
  {"file": "words/water.wav", "text": "water", "category": "lesson_word", "focus": "w", "type": "human_native"},
  {"file": "words/street.wav", "text": "street", "category": "lesson_word", "focus": "str-", "type": "human_native"},
  {"file": "words/strength.wav", "text": "strength", "category": "lesson_word", "focus": "ŋθ", "type": "human_native"},
  {"file": "words/beautiful.wav", "text": "beautiful", "category": "lesson_word", "focus": "stress", "type": "human_native"},
  {"file": "synthetic/syn_sheep.wav", "text": "sheep", "category": "synthetic_control", "type": "synthetic_espeak"},
  {"file": "synthetic/syn_ship.wav", "text": "ship", "category": "synthetic_control", "type": "synthetic_espeak"},
  {"file": "synthetic/syn_three.wav", "text": "three", "category": "synthetic_control", "type": "synthetic_espeak"},
  {"file": "synthetic/syn_tree.wav", "text": "tree", "category": "synthetic_control", "type": "synthetic_espeak"},
  {"file": "synthetic/syn_thin.wav", "text": "thin", "category": "synthetic_control", "type": "synthetic_espeak"},
  {"file": "synthetic/syn_sin.wav", "text": "sin", "category": "synthetic_control", "type": "synthetic_espeak"},
  {"file": "synthetic/syn_rice.wav", "text": "rice", "category": "synthetic_control", "type": "synthetic_espeak"},
  {"file": "synthetic/syn_lice.wav", "text": "lice", "category": "synthetic_control", "type": "synthetic_espeak"},
  {"file": "synthetic/syn_very.wav", "text": "very", "category": "synthetic_control", "type": "synthetic_espeak"},
  {"file": "synthetic/syn_berry.wav", "text": "berry", "category": "synthetic_control", "type": "synthetic_espeak"},
  {"file": "synthetic/syn_wine.wav", "text": "wine", "category": "synthetic_control", "type": "synthetic_espeak"},
  {"file": "synthetic/syn_vine.wav", "text": "vine", "category": "synthetic_control", "type": "synthetic_espeak"},
  {"file": "synthetic/syn_feel.wav", "text": "feel", "category": "synthetic_control", "type": "synthetic_espeak"},
  {"file": "synthetic/syn_fill.wav", "text": "fill", "category": "synthetic_control", "type": "synthetic_espeak"}
];

/* ------------------------------------------------------------------ helpers */

function colorFor(score) {
  if (score >= THRESHOLDS.good) return "var(--good)";
  if (score >= THRESHOLDS.fair) return "var(--fair)";
  return "var(--poor)";
}

function setStatus(msg, isError = false) {
  const el = $("status");
  if (!el) return;
  el.textContent = msg;
  el.classList.toggle("err", isError);
}

async function api(path, opts) {
  const cleanPath = path.startsWith("/") ? path : "/" + path;
  const res = await fetch(API + cleanPath, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res;
}

/* ------------------------------------------------------------------ playback */

let playCtx = null;
const audioCtx = () => (playCtx ||= new (window.AudioContext || window.webkitAudioContext)());

let currentAudioEl = null;
let currentPlayingBtn = null;

function playUrl(url, triggerBtn = null) {
  if (currentAudioEl) {
    currentAudioEl.pause();
    currentAudioEl = null;
    if (currentPlayingBtn) {
      currentPlayingBtn.innerHTML = currentPlayingBtn.dataset.originalHtml || "▶ Listen";
      currentPlayingBtn = null;
    }
  }

  if (triggerBtn) {
    if (!triggerBtn.dataset.originalHtml) {
      triggerBtn.dataset.originalHtml = triggerBtn.innerHTML;
    }
  }

  const el = new Audio(url);
  currentAudioEl = el;
  if (triggerBtn) {
    currentPlayingBtn = triggerBtn;
    triggerBtn.innerHTML = "⏹ Stop";
  }

  el.onended = () => {
    if (triggerBtn) triggerBtn.innerHTML = triggerBtn.dataset.originalHtml || "▶ Listen";
    currentAudioEl = null;
    currentPlayingBtn = null;
  };

  el.onerror = () => {
    if (triggerBtn) triggerBtn.innerHTML = triggerBtn.dataset.originalHtml || "▶ Listen";
    currentAudioEl = null;
    currentPlayingBtn = null;
    setStatus("Playback failed for audio clip", true);
  };

  el.play().catch((e) => {
    if (triggerBtn) triggerBtn.innerHTML = triggerBtn.dataset.originalHtml || "▶ Listen";
    currentAudioEl = null;
    currentPlayingBtn = null;
    setStatus("Playback failed: " + e.message, true);
  });
}

function playIdeal(text, speed = "normal") {
  playUrl(`${API}/api/tts?speed=${speed}&text=${encodeURIComponent(text)}`);
}

/** Play a slice of the scored recording (word-level playback). */
function playMine(startMs, endMs) {
  if (!MY_BUFFER) return;
  const ctx = audioCtx();
  const src = ctx.createBufferSource();
  src.buffer = MY_BUFFER;
  src.connect(ctx.destination);
  if (startMs == null || endMs == null) {
    src.start();
  } else {
    const pad = 0.04;
    const from = Math.max(0, startMs / 1000 - pad);
    const dur = Math.max(0.08, (endMs - startMs) / 1000 + pad * 2);
    src.start(0, from, Math.min(dur, MY_BUFFER.duration - from));
  }
}

/* ------------------------------------------------------------------ recorder */

const WORKLET_SRC = `
class RecProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch && ch.length) this.port.postMessage(new Float32Array(ch));
    return true;
  }
}
registerProcessor('rec-processor', RecProcessor);
`;

const MAX_SECONDS = 15;

class Recorder {
  constructor() {
    this.recording = false;
    this.chunks = [];
    this.ctx = null;
    this.stream = null;
    this.nodes = [];
  }

  async start(onLevel) {
    this.chunks = [];
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    const Ctx = window.AudioContext || window.webkitAudioContext;
    try { this.ctx = new Ctx({ sampleRate: 16000 }); }
    catch (_) { this.ctx = new Ctx(); }
    if (this.ctx.state === "suspended") await this.ctx.resume();

    const source = this.ctx.createMediaStreamSource(this.stream);
    const sink = this.ctx.createGain();
    sink.gain.value = 0;
    sink.connect(this.ctx.destination);

    const push = (data) => {
      this.chunks.push(data);
      if (onLevel) {
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        onLevel(Math.sqrt(sum / data.length));
      }
    };

    let node;
    if (this.ctx.audioWorklet) {
      const url = URL.createObjectURL(new Blob([WORKLET_SRC], { type: "application/javascript" }));
      await this.ctx.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);
      node = new AudioWorkletNode(this.ctx, "rec-processor");
      node.port.onmessage = (e) => push(e.data);
    } else {
      node = this.ctx.createScriptProcessor(4096, 1, 1);
      node.onaudioprocess = (e) => push(new Float32Array(e.inputBuffer.getChannelData(0)));
    }

    source.connect(node);
    node.connect(sink);
    this.nodes = [source, node, sink];
    this.recording = true;
    this.sampleRate = this.ctx.sampleRate;
  }

  async stop() {
    this.recording = false;
    this.nodes.forEach((n) => { try { n.disconnect(); } catch (_) {} });
    this.nodes = [];
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    const rate = this.sampleRate || 16000;
    if (this.ctx) { try { await this.ctx.close(); } catch (_) {} this.ctx = null; }

    let total = 0;
    this.chunks.forEach((c) => (total += c.length));
    const pcm = new Float32Array(total);
    let off = 0;
    this.chunks.forEach((c) => { pcm.set(c, off); off += c.length; });
    return encodeWav(pcm, rate);
  }
}

function encodeWav(samples, sampleRate) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i)); };

  str(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  str(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);            // PCM
  view.setUint16(22, 1, true);            // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  str(36, "data");
  view.setUint32(40, samples.length * 2, true);

  let o = 44;
  for (let i = 0; i < samples.length; i++, o += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

const recorder = new Recorder();
let autoStopTimer = null;

/* ------------------------------------------------------------------ target */

async function setTarget(text, skipClearResults = false) {
  TARGET = (text || "").trim();
  $("targetText").textContent = TARGET || "—";
  $("targetIpa").textContent = "";

  if (!skipClearResults) {
    $("results").classList.add("hidden");
    $("coach").classList.add("hidden");
    $("detail").classList.add("hidden");
    $("playMine").disabled = true;
    $("testedSampleBadge").innerHTML = "";
    MY_BUFFER = null;
    LAST = null;
  }

  if (!TARGET) return;

  try {
    const data = await (await api("/api/phonemize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: TARGET }),
    })).json();
    $("targetIpa").textContent = "/ " + data.ipa + " /";
    if (!skipClearResults) {
      setStatus("Target set. Listen to ideal audio or test with a sample.");
    }
  } catch (e) {
    $("targetIpa").textContent = "";
    setStatus("could not phonemize: " + e.message, true);
  }
}

/* ------------------------------------------------------------------ scoring flow */

async function submit(blob, sampleLabel = "") {
  setStatus("Scoring audio… (wav2vec2 CTC forced alignment + GOP)");
  const fd = new FormData();
  fd.append("audio", blob, "recording.wav");
  fd.append("text", TARGET);

  try {
    const payload = await (await api("/api/assess", { method: "POST", body: fd })).json();
    THRESHOLDS = payload.thresholds || THRESHOLDS;
    LAST = payload;
    await loadMyRecording(payload.recording_id);
    render(payload, sampleLabel);
    setStatus(`Assessed in ${payload.duration_s}s · ${payload.speech_rate} phones/sec · Overall: ${payload.overall}/100`);
  } catch (e) {
    setStatus("Assessment failed: " + e.message, true);
  }
}

async function loadMyRecording(id) {
  MY_BUFFER = null;
  $("playMine").disabled = true;
  if (!id) return;
  try {
    const buf = await (await api(`/api/recording/${id}`)).arrayBuffer();
    MY_BUFFER = await audioCtx().decodeAudioData(buf);
    $("playMine").disabled = false;
  } catch (_) { /* playback is non-fatal */ }
}

/* ------------------------------------------------------------------ rendering */

function setBar(barId, numId, value) {
  const bar = $(barId);
  if (!bar) return;
  const val = Math.max(0, Math.min(100, Math.round(value)));
  bar.style.width = val + "%";
  bar.style.background = colorFor(val);
  $(numId).textContent = val + "%";
}

function render(p, sampleLabel = "") {
  $("results").classList.remove("hidden");

  // Sample tag
  const tagContainer = $("testedSampleBadge");
  if (sampleLabel) {
    tagContainer.innerHTML = `<span class="tested-sample-tag">Tested: <strong>${sampleLabel}</strong></span>`;
  } else {
    tagContainer.innerHTML = "";
  }

  // Smooth Gauge Fill
  const arc = $("gaugeArc");
  const C = 2 * Math.PI * 52; // radius 52 -> perimeter 326.7
  arc.setAttribute("stroke-dasharray", C.toFixed(1));
  arc.setAttribute("stroke-dashoffset", (C * (1 - p.overall / 100)).toFixed(1));
  arc.setAttribute("stroke", colorFor(p.overall));
  $("overall").textContent = p.overall;
  $("overall").style.color = colorFor(p.overall);

  // Bars
  setBar("barAccuracy", "numAccuracy", p.accuracy);
  setBar("barCompleteness", "numCompleteness", p.completeness);
  setBar("barFluency", "numFluency", p.fluency);
  setBar("barVowels", "numVowels", p.breakdown ? p.breakdown.vowels : 0);
  setBar("barConsonants", "numConsonants", p.breakdown ? p.breakdown.consonants : 0);

  // Words
  const words = $("words");
  words.innerHTML = "";
  p.words.forEach((w, i) => {
    const el = document.createElement("div");
    el.className = "word-tile";
    el.style.borderTopColor = colorFor(w.score);
    el.innerHTML = `<div class="w"></div>
                    <div class="p ipa"></div>
                    <div class="s"></div>`;
    el.querySelector(".w").textContent = w.text;
    el.querySelector(".p").textContent = "/" + w.ipa + "/";
    const s = el.querySelector(".s");
    s.textContent = w.score + " pts";
    s.style.color = colorFor(w.score);
    el.onclick = () => showWord(i);
    words.appendChild(el);
  });

  $("refIpa").textContent = p.reference_ipa;
  $("hypIpa").textContent = p.recognized_ipa || "(no speech recognized)";
  $("meta").textContent = p.forced_aligned
    ? ""
    : "Note: forced alignment failed (recording shorter than the phrase) — scores use recognition only.";

  // Hints
  const hints = $("hints");
  hints.innerHTML = "";
  if (p.feedback && p.feedback.length) {
    $("coach").classList.remove("hidden");
    p.feedback.forEach((h) => {
      const el = document.createElement("div");
      el.className = "hint-item";
      el.textContent = h;
      hints.appendChild(el);
    });
  } else {
    $("coach").classList.add("hidden");
  }

  if (p.words.length) showWord(0);
}

function showWord(idx) {
  if (!LAST || !LAST.words[idx]) return;
  ACTIVE_WORD = idx;
  const w = LAST.words[idx];

  document.querySelectorAll(".word-tile").forEach((el, i) => {
    el.classList.toggle("active", i === idx);
  });

  const d = $("detail");
  d.classList.remove("hidden");
  d.innerHTML = "";

  const head = document.createElement("div");
  head.className = "phoneme-head";
  head.innerHTML = `<h3>${w.text} <span class="ipa" style="color:var(--text-muted);font-weight:normal">/${w.ipa}/</span></h3>
                    <div style="display:flex;align-items:center;gap:10px">
                      <span style="color:${colorFor(w.score)};font-weight:700;font-size:16px">${w.score}/100</span>
                      <button id="playWordSlice" class="btn btn-secondary" style="padding:4px 10px;font-size:12px">▶ Play word slice</button>
                    </div>`;
  d.appendChild(head);

  $("playWordSlice").onclick = () => playMine(w.start_ms, w.end_ms);

  const phones = document.createElement("div");
  phones.className = "phoneme-tiles";
  w.phones.forEach((ph) => {
    const p = document.createElement("div");
    p.className = "phone-tile";
    p.style.borderColor = colorFor(ph.score);
    const sub = ph.status === "sub" && ph.heard
              ? `<div class="heard" style="color:var(--poor);background:var(--poor-bg)">heard /${ph.heard}/</div>`
              : ph.status === "missing"
              ? `<div class="heard" style="color:var(--poor);background:var(--poor-bg)">&times; missing</div>`
              : `<div class="heard" style="color:var(--good);background:var(--good-bg)">match</div>`;
    p.innerHTML = `<div class="sym ipa">${ph.phone}</div>
                   <div class="sc">${ph.score}</div>
                   ${sub}`;
    phones.appendChild(p);
  });
  d.appendChild(phones);
}

/* ------------------------------------------------------------------ sample audio library */

async function loadSamples() {
  $("sampleCount").textContent = SAMPLES.length;
  renderSampleList();

  try {
    const res = await api(`/api/samples?t=${Date.now()}`);
    const data = await res.json();
    if (data.samples && data.samples.length > 0) {
      SAMPLES = data.samples;
      $("sampleCount").textContent = SAMPLES.length;
      renderSampleList();
    }
  } catch (e) {
    console.warn("Could not refresh live samples, using embedded manifest:", e);
  }
}

function renderSampleList() {
  const container = $("sampleList");
  if (!container) return;
  container.innerHTML = "";

  // Prioritize sentences first when viewing All or filtered
  const filtered = SAMPLES.filter((s) => {
    const matchesCategory = ACTIVE_FILTER === "all" || s.category === ACTIVE_FILTER;
    const matchesSearch = !SEARCH_QUERY ||
      s.text.toLowerCase().includes(SEARCH_QUERY) ||
      (s.focus && s.focus.toLowerCase().includes(SEARCH_QUERY)) ||
      (s.file && s.file.toLowerCase().includes(SEARCH_QUERY)) ||
      (s.speaker && s.speaker.toLowerCase().includes(SEARCH_QUERY));
    return matchesCategory && matchesSearch;
  }).sort((a, b) => {
    if (ACTIVE_FILTER === "all") {
      if (a.category === "sentence" && b.category !== "sentence") return -1;
      if (b.category === "sentence" && a.category !== "sentence") return 1;
    }
    return 0;
  });

  if (filtered.length === 0) {
    container.innerHTML = `<div class="status-text" style="padding:20px;text-align:center">No samples matching filter.</div>`;
    return;
  }

  filtered.forEach((sample) => {
    const card = document.createElement("div");
    const isSentence = sample.category === "sentence";
    card.className = "sample-card" + (isSentence ? " is-sentence" : "");

    const badgeText = sample.focus ? `/${sample.focus}/` : (sample.speaker ? sample.speaker : "Sentence");
    const typeLabel = sample.type === "human_native" ? "Human Native"
                    : sample.type === "human" ? (sample.speaker ? sample.speaker : "CMU Arctic")
                    : "eSpeak TTS";

    const audioUrl = `${API}/api/samples/audio/${sample.file}`;

    card.innerHTML = `
      <div class="sample-top">
        <span class="sample-name">${sample.text}</span>
        ${badgeText ? `<span class="sample-focus">${badgeText}</span>` : ""}
      </div>
      <div class="sample-info">
        <span>${isSentence ? "🎙️ " : ""}${typeLabel}</span>
        <span>&middot;</span>
        <span>${sample.file.split("/").pop()}</span>
      </div>
      <div class="sample-actions">
        <button class="btn-sample btn-listen" data-url="${audioUrl}">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          <span>Listen</span>
        </button>
        <button class="btn-sample score btn-test-sample">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          <span>Test &amp; Score</span>
        </button>
        <button class="btn-sample btn-set-target">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>
          <span>Target</span>
        </button>
      </div>
    `;

    // Listen Button
    const listenBtn = card.querySelector(".btn-listen");
    listenBtn.onclick = (e) => {
      e.stopPropagation();
      playUrl(audioUrl, listenBtn);
    };

    // Test & Score Button
    const testBtn = card.querySelector(".btn-test-sample");
    testBtn.onclick = async (e) => {
      e.stopPropagation();
      document.querySelectorAll(".sample-card").forEach((c) => c.classList.remove("active-test"));
      card.classList.add("active-test");
      await testSampleAudio(sample);
    };

    // Set Target Button
    const setTargetBtn = card.querySelector(".btn-set-target");
    setTargetBtn.onclick = (e) => {
      e.stopPropagation();
      setTarget(sample.text);
    };

    container.appendChild(card);
  });
}

async function testSampleAudio(sample) {
  try {
    setStatus(`Loading sample '${sample.text}'...`);
    await setTarget(sample.text, true);

    const audioUrl = `${API}/api/samples/audio/${sample.file}`;
    const res = await fetch(audioUrl);
    if (!res.ok) throw new Error("Could not fetch sample audio file");
    const blob = await res.blob();

    const label = `${sample.text} (${sample.file.split("/").pop()})`;
    await submit(blob, label);
  } catch (e) {
    setStatus("Error testing sample: " + e.message, true);
  }
}

/* ------------------------------------------------------------------ lessons */

async function loadLessons() {
  try {
    const data = await (await api(`/api/lessons?t=${Date.now()}`)).json();
    const c = $("lessons");
    if (!c) return;
    c.innerHTML = "";
    data.lessons.forEach((l) => {
      const d = document.createElement("details");
      d.className = "lesson";
      d.innerHTML = `
        <summary>
          <span>${l.title}</span>
          <span class="focus ipa">${l.focus}</span>
        </summary>
        <div class="why">${l.why}</div>
        <div class="chips"></div>
      `;
      const chips = d.querySelector(".chips");

      (l.minimal_pairs || []).forEach((pair) => {
        const btn = document.createElement("button");
        btn.className = "chip pair";
        btn.textContent = pair.join(" / ");
        btn.onclick = () => setTarget(pair[0]);
        chips.appendChild(btn);
      });

      (l.items || []).forEach((item) => {
        const btn = document.createElement("button");
        btn.className = "chip";
        btn.textContent = item;
        btn.onclick = () => setTarget(item);
        chips.appendChild(btn);
      });

      (l.sentences || []).forEach((s) => {
        const btn = document.createElement("button");
        btn.className = "chip sentence";
        btn.textContent = s;
        btn.onclick = () => setTarget(s);
        chips.appendChild(btn);
      });

      c.appendChild(d);
    });
  } catch (e) {
    const c = $("lessons");
    if (c) c.innerHTML = `<div class="status-text err">Could not load lessons: ${e.message}</div>`;
  }
}

/* ------------------------------------------------------------------ health check */

async function checkHealth() {
  const el = $("health");
  if (!el) return;
  try {
    const h = await (await api(`/api/health?t=${Date.now()}`)).json();
    if (h.status === "ok") {
      el.className = "health-pill ok";
      el.querySelector(".label").textContent = "Ready " + (h.asr_loaded ? "(model warm)" : "(model ready)");
    } else {
      el.className = "health-pill bad";
      el.querySelector(".label").textContent = "espeak-ng missing";
    }
  } catch (e) {
    el.className = "health-pill bad";
    el.querySelector(".label").textContent = "API offline";
  }
}

/* ------------------------------------------------------------------ UI wiring */

function setupTabs() {
  const tabs = [
    { btn: $("tabSamples"), panel: $("panelSamples") },
    { btn: $("tabLessons"), panel: $("panelLessons") },
    { btn: $("tabCustom"), panel: $("panelCustom") },
  ];

  tabs.forEach(({ btn, panel }) => {
    if (!btn || !panel) return;
    btn.onclick = () => {
      tabs.forEach((t) => {
        if (t.btn) t.btn.classList.remove("active");
        if (t.panel) t.panel.classList.add("hidden");
      });
      btn.classList.add("active");
      panel.classList.remove("hidden");
    };
  });
}

function setupFilters() {
  const pills = document.querySelectorAll("#sampleFilterPills .pill");
  pills.forEach((pill) => {
    pill.onclick = () => {
      pills.forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      ACTIVE_FILTER = pill.dataset.filter;
      renderSampleList();
    };
  });

  const searchInput = $("sampleSearch");
  const clearBtn = $("clearSearchBtn");

  if (searchInput) {
    searchInput.oninput = (e) => {
      SEARCH_QUERY = (e.target.value || "").trim().toLowerCase();
      if (clearBtn) clearBtn.classList.toggle("hidden", !SEARCH_QUERY);
      renderSampleList();
    };
  }

  if (clearBtn) {
    clearBtn.onclick = () => {
      if (searchInput) searchInput.value = "";
      SEARCH_QUERY = "";
      clearBtn.classList.add("hidden");
      renderSampleList();
    };
  }
}

function setupDragAndDrop() {
  const dropZone = $("targetSection");
  if (!dropZone) return;

  ["dragenter", "dragover"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.add("drag-over");
    });
  });

  ["dragleave", "drop"].forEach((eventName) => {
    dropZone.addEventListener(eventName, (e) => {
      e.preventDefault();
      e.stopPropagation();
      dropZone.classList.remove("drag-over");
    });
  });

  dropZone.addEventListener("drop", async (e) => {
    const dt = e.dataTransfer;
    const files = dt.files;
    if (files && files.length > 0) {
      const file = files[0];
      if (!TARGET) {
        setStatus("Please set a target phrase before dropping audio.", true);
        return;
      }
      setStatus(`Processing dropped file: ${file.name}...`);
      await submit(file, `Dropped: ${file.name}`);
    }
  });

  // Upload button & input
  const uploadBtn = $("uploadAudioBtn");
  const fileInput = $("audioFileInput");
  if (uploadBtn && fileInput) {
    uploadBtn.onclick = () => fileInput.click();

    fileInput.onchange = async () => {
      if (fileInput.files && fileInput.files.length > 0) {
        const file = fileInput.files[0];
        if (!TARGET) {
          setStatus("Please set a target phrase before uploading audio.", true);
          return;
        }
        setStatus(`Processing uploaded file: ${file.name}...`);
        await submit(file, `Uploaded: ${file.name}`);
        fileInput.value = "";
      }
    };
  }
}

function setupControls() {
  if ($("setCustom")) $("setCustom").onclick = () => setTarget($("custom").value);
  if ($("playIdeal")) $("playIdeal").onclick = () => { if (TARGET) playIdeal(TARGET, "normal"); };
  if ($("playSlow")) $("playSlow").onclick = () => { if (TARGET) playIdeal(TARGET, "slow"); };
  if ($("playMine")) $("playMine").onclick = () => playMine();

  // Record button
  const recBtn = $("record");
  const recLabel = $("recLabel");
  const levelMeter = $("level");
  const meterTrack = $("meterTrack");

  if (recBtn) {
    recBtn.onclick = async () => {
      if (!TARGET) {
        setStatus("Pick or type a target phrase first.", true);
        return;
      }

      if (recorder.recording) {
        clearTimeout(autoStopTimer);
        recBtn.disabled = true;
        if (meterTrack) meterTrack.classList.remove("live");
        recBtn.classList.remove("recording");
        if (recLabel) recLabel.textContent = "Record Mic";
        try {
          const wav = await recorder.stop();
          await submit(wav, "Microphone recording");
        } catch (e) {
          setStatus("recording failed: " + e.message, true);
        } finally {
          recBtn.disabled = false;
        }
      } else {
        try {
          await recorder.start((lvl) => {
            if (levelMeter) levelMeter.style.width = Math.min(100, Math.round(lvl * 300)) + "%";
          });
          if (meterTrack) meterTrack.classList.add("live");
          recBtn.classList.add("recording");
          if (recLabel) recLabel.textContent = "Stop Recording";
          setStatus("Listening… speak now.");
          autoStopTimer = setTimeout(() => {
            if (recorder.recording) recBtn.click();
          }, MAX_SECONDS * 1000);
        } catch (e) {
          setStatus("microphone error: " + e.message, true);
        }
      }
    };
  }
}

/* ------------------------------------------------------------------ init */

window.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupFilters();
  setupDragAndDrop();
  setupControls();
  checkHealth();
  loadSamples();
  loadLessons();

  // Initial target
  setTarget("She sells seashells by the seashore.");
});
