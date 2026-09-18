const form = document.getElementById('workForm');
const healthBtn = document.getElementById('healthBtn');
const statusEl = document.getElementById('status');
const outputEl = document.getElementById('optimizedText');
const rawJsonEl = document.getElementById('rawJson');
const flagsEl = document.getElementById('flags');
const artifactsEl = document.getElementById('artifacts');
const benchStatusEl = document.getElementById('benchStatus');
const benchCardsEl = document.getElementById('benchCards');
const benchSummaryEl = document.getElementById('benchSummary');
const requestAnalysisEl = document.getElementById('requestAnalysis');
const retrievalListEl = document.getElementById('retrievalList');
const refreshBenchBtn = document.getElementById('refreshBenchBtn');
const instructionsGroup = document.getElementById('instructionsGroup');
const formatGroup = document.getElementById('formatGroup');
const imageGroup = document.getElementById('imageGroup');
const imageFiles = document.getElementById('imageFiles');
const imageSelection = document.getElementById('imageSelection');

function metric(label, value, helper = '') {
  return { label, value, helper };
}

function setStatus(kind, text) {
  statusEl.className = `status ${kind}`;
  statusEl.textContent = text;
}

function headers() {
  return {
    'Content-Type': 'application/json',
    'X-User-Id': document.getElementById('userId').value.trim(),
    'X-User-Role': document.getElementById('userRole').value.trim(),
  };
}

function instructionLines() {
  return document.getElementById('instructions')
    .value
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean);
}

function selectedFormats() {
  const out = [];
  if (document.getElementById('fmtPdf').checked) out.push('pdf');
  if (document.getElementById('fmtDocx').checked) out.push('docx');
  return out;
}

function workspaceHints() {
  return (document.getElementById('workspaceHints').value || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error(`Failed to read ${file.name}`));
    reader.readAsDataURL(file);
  });
}

async function selectedImagesPayload() {
  const files = Array.from(imageFiles.files || []);
  const payload = [];
  for (const file of files) {
    const dataUrl = await fileToDataUrl(file);
    payload.push({
      image_name: file.name,
      mime_type: file.type || 'image/png',
      content_base64: dataUrl,
    });
  }
  return payload;
}

async function downloadArtifact(path, filename) {
  const res = await fetch(path, { headers: headers() });
  if (!res.ok) {
    throw new Error(`Download failed: ${res.status}`);
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function renderArtifacts(items) {
  artifactsEl.innerHTML = '';
  for (const item of items || []) {
    const wrap = document.createElement('div');
    wrap.className = 'artifact-item';

    const meta = document.createElement('div');
    meta.textContent = `${item.filename} (${item.format.toUpperCase()}, ${item.size_bytes} bytes)`;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = 'Download';
    btn.addEventListener('click', async () => {
      try {
        setStatus('loading', `Downloading ${item.filename}...`);
        await downloadArtifact(item.download_path, item.filename);
        setStatus('ok', `Downloaded ${item.filename}`);
      } catch (err) {
        setStatus('error', String(err));
      }
    });

    wrap.appendChild(meta);
    wrap.appendChild(btn);
    artifactsEl.appendChild(wrap);
  }
}

function renderFlags(flags) {
  flagsEl.innerHTML = '';
  for (const flag of flags || []) {
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.textContent = flag;
    flagsEl.appendChild(chip);
  }
}

function renderMetricCards(items) {
  benchCardsEl.innerHTML = '';
  for (const item of items) {
    const card = document.createElement('div');
    card.className = 'metric-card';

    const label = document.createElement('div');
    label.className = 'metric-label';
    label.textContent = item.label;

    const value = document.createElement('div');
    value.className = 'metric-value';
    value.textContent = item.value;

    const helper = document.createElement('div');
    helper.className = 'metric-helper';
    helper.textContent = item.helper || '';

    card.appendChild(label);
    card.appendChild(value);
    card.appendChild(helper);
    benchCardsEl.appendChild(card);
  }
}

function analyzeDocumentResponse(data) {
  const text = String(data.optimized_text || '');
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean);
  const headingCount = lines.filter((line) => line.startsWith('#') || /^\*\*.+\*\*$/.test(line) || line.endsWith(':')).length;
  const bulletCount = lines.filter((line) => /^[-*•]\s+/.test(line)).length;
  const artifactBytes = (data.artifacts || []).reduce((sum, item) => sum + Number(item.size_bytes || 0), 0);
  const retrievalStats = data.retrieval_stats || {};

  return {
    characters: text.length,
    sections: headingCount,
    bullets: bulletCount,
    artifacts: (data.artifacts || []).length,
    artifactBytes,
    groundedSources: (data.workspace_sources || []).length,
    retrievedChunks: Number(retrievalStats.returned_chunks || 0),
    retrievalLatencyMs: Number(retrievalStats.retrieval_latency_ms || 0),
    cacheHits: Number(retrievalStats.cache_hits || 0),
    cacheMisses: Number(retrievalStats.cache_misses || 0),
    topScore: Number(retrievalStats.top_score || 0),
  };
}

function renderRequestAnalysis(data) {
  const analysis = analyzeDocumentResponse(data);
  requestAnalysisEl.textContent = JSON.stringify(analysis, null, 2);
}

function renderRetrievalChunks(chunks) {
  retrievalListEl.innerHTML = '';
  for (const item of chunks || []) {
    const wrap = document.createElement('div');
    wrap.className = 'artifact-item';

    const meta = document.createElement('div');
    meta.innerHTML = `<strong>${item.source}</strong> · score ${Number(item.score || 0).toFixed(3)}<br>${item.preview || ''}`;

    wrap.appendChild(meta);
    retrievalListEl.appendChild(wrap);
  }
}

async function refreshBenchmarks() {
  benchStatusEl.textContent = 'Loading benchmark snapshot...';
  try {
    const res = await fetch('/benchmarks');
    const data = await res.json();
    const summary = data.summary || {};
    const rag = data.rag_config || {};
    renderMetricCards([
      metric('Pass Rate', summary.pass_rate ?? '-', `mode ${data.mode || 'n/a'}`),
      metric('Coverage', summary.avg_must_include_coverage ?? '-', 'must-include hit rate'),
      metric('Latency', summary.avg_latency_ms ?? '-', 'avg request ms'),
      metric('Retrieval', summary.avg_retrieval_latency_ms ?? '-', 'avg retrieval ms'),
      metric('Grounded Sources', summary.avg_grounded_source_count ?? '-', 'avg sources per run'),
      metric('Cache Hits', summary.avg_cache_hits ?? '-', `top-k ${rag.top_k_chunks ?? '-'}`),
    ]);
    benchSummaryEl.textContent = JSON.stringify({ summary, rag_config: rag }, null, 2);
    benchStatusEl.textContent = data.status === 'available'
      ? 'Benchmark snapshot loaded.'
      : 'No benchmark report found yet. Run the eval harness to populate this panel.';
  } catch (err) {
    benchStatusEl.textContent = `Benchmark load failed: ${String(err)}`;
  }
}

async function runWork(event) {
  event.preventDefault();
  outputEl.textContent = '';
  rawJsonEl.textContent = '';
  artifactsEl.innerHTML = '';
  flagsEl.innerHTML = '';

  const prompt = document.getElementById('userPrompt').value.trim();
  if (!prompt) {
    setStatus('error', 'Prompt is required.');
    return;
  }

  const payloadCommon = {
    document_id: document.getElementById('documentId').value.trim(),
    domain: document.getElementById('domain').value.trim() || 'general',
    objective: document.getElementById('objective').value.trim() || 'Optimize and produce publication-ready output',
    source_text: document.getElementById('sourceText').value,
  };

  const imageInputs = await selectedImagesPayload();
  const body = {
    ...payloadCommon,
    user_prompt: prompt,
    instructions: instructionLines(),
    detail_level: document.getElementById('detailLevel').value,
    output_formats: selectedFormats(),
    include_inline_artifacts: document.getElementById('inlineArtifacts').checked,
    image_inputs: imageInputs,
    use_workspace_context: document.getElementById('useWorkspaceContext').checked,
    workspace_file_hints: workspaceHints(),
  };

  setStatus('loading', 'Generating document...');

  try {
    const res = await fetch('/compose', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify(body),
    });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
    }

    outputEl.textContent = data.optimized_text || '';
    rawJsonEl.textContent = JSON.stringify(data, null, 2);
    renderFlags(data.policy_flags || []);
    renderArtifacts(data.artifacts || []);
      renderRequestAnalysis(data);
      renderRetrievalChunks(data.retrieval_chunks || []);
    setStatus('ok', 'Document generated successfully');
  } catch (err) {
    setStatus('error', String(err));
  }
}

async function checkHealth() {
  setStatus('loading', 'Checking health...');
  try {
    const res = await fetch('/health');
    const data = await res.json();
    setStatus('ok', `Health: ${data.status} (${data.env})`);
  } catch (err) {
    setStatus('error', String(err));
  }
}

form.addEventListener('submit', runWork);
healthBtn.addEventListener('click', checkHealth);
refreshBenchBtn.addEventListener('click', refreshBenchmarks);
imageFiles.addEventListener('change', () => {
  const count = (imageFiles.files || []).length;
  imageSelection.textContent = count ? `${count} image(s) selected` : 'No images selected.';
});
instructionsGroup.style.display = 'block';
formatGroup.style.display = 'none';
imageGroup.style.display = 'block';
refreshBenchmarks();
